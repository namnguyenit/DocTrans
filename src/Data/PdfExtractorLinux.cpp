#include "readDoc/Data/PdfExtractor.h"

#include <QCoreApplication>
#include <QDir>
#include <QFileInfo>
#include <QJsonArray>
#include <QJsonDocument>
#include <QJsonObject>
#include <QPdfDocument>
#include <QProcess>
#include <QRegularExpression>
#include <QStandardPaths>
#include <QTemporaryFile>

namespace {
QString resourceDirectory() {
    const QString configured = qEnvironmentVariable("READDOC_RESOURCE_DIR");
    if (!configured.isEmpty() && QDir(configured).exists()) return configured;
    const QDir executableDir{QCoreApplication::applicationDirPath()};
    const QStringList candidates = {
        executableDir.absoluteFilePath("../share/readDoc"),
        executableDir.absoluteFilePath("resources"),
        QDir::current().absoluteFilePath("src/Data"),
    };
    for (const QString &candidate : candidates) {
        if (QFileInfo::exists(QDir(candidate).filePath("extract_pdf.py"))) {
            return QDir(candidate).absolutePath();
        }
    }
    return {};
}

QString pythonExecutable() {
    const QString configured = qEnvironmentVariable("READDOC_PYTHON");
    if (!configured.isEmpty() && QFileInfo::exists(configured)) return configured;

    QDir appDir(QCoreApplication::applicationDirPath());
    for (int i = 0; i < 8; ++i) {
        const QStringList venvCandidates = {
            appDir.filePath(".venv/Scripts/python.exe"),
            appDir.filePath("venv/Scripts/python.exe"),
            appDir.filePath(".venv/bin/python3"),
            appDir.filePath("venv/bin/python3"),
            appDir.filePath(".venv/bin/python"),
            appDir.filePath("venv/bin/python"),
        };
        for (const QString &candidate : venvCandidates) {
            if (QFileInfo::exists(candidate)) {
                return QDir::cleanPath(candidate);
            }
        }
        if (!appDir.cdUp()) break;
    }

    QDir workDir(QDir::currentPath());
    for (int i = 0; i < 8; ++i) {
        const QStringList venvCandidates = {
            workDir.filePath(".venv/Scripts/python.exe"),
            workDir.filePath("venv/Scripts/python.exe"),
            workDir.filePath(".venv/bin/python3"),
            workDir.filePath("venv/bin/python3"),
        };
        for (const QString &candidate : venvCandidates) {
            if (QFileInfo::exists(candidate)) {
                return QDir::cleanPath(candidate);
            }
        }
        if (!workDir.cdUp()) break;
    }

#ifdef Q_OS_WIN
    return "python";
#else
    if (QFileInfo::exists("/opt/homebrew/bin/python3")) return "/opt/homebrew/bin/python3";
    if (QFileInfo::exists("/usr/local/bin/python3")) return "/usr/local/bin/python3";
    return "python3";
#endif
}

bool needsLocalOcr(const QString &pageContent) {
    QString visible = pageContent;
    static const QRegularExpression marker(
        QStringLiteral("\\[\\[READDOC_(?:IMAGE|TABLE|CODE|TOC):[A-Za-z0-9+/=]+\\]\\]"));
    visible.remove(marker);
    int letters = 0;
    int replacements = 0;
    for (const QChar ch : visible) {
        if (ch.isLetter()) ++letters;
        if (ch == QChar::ReplacementCharacter) ++replacements;
    }
    return letters < 20 || (letters > 0 && replacements * 20 > letters);
}

QSizeF pagePointSize(const QPdfDocument &document, int pageIndex) {
#if QT_VERSION < QT_VERSION_CHECK(6, 4, 0)
    return document.pageSize(pageIndex);
#else
    return document.pagePointSize(pageIndex);
#endif
}

QString recognizePageLocally(QPdfDocument &document, int pageIndex) {
    const QString tesseract = QStandardPaths::findExecutable("tesseract");
    if (tesseract.isEmpty()) return {};
    const QSizeF points = pagePointSize(document, pageIndex);
    if (points.isEmpty()) return {};
    const qreal scale = qMin<qreal>(3.0, 2200.0 /
        qMax<qreal>(1.0, qMax(points.width(), points.height())));
    const QSize imageSize(qMax(1, qRound(points.width() * scale)),
                          qMax(1, qRound(points.height() * scale)));
    const QImage image = document.render(pageIndex, imageSize);
    if (image.isNull()) return {};

    QTemporaryFile temporary(QDir::tempPath() + "/readDoc-ocr-XXXXXX.png");
    if (!temporary.open() || !image.save(&temporary, "PNG")) return {};
    temporary.flush();

    QProcess process;
    process.start(tesseract, {
        temporary.fileName(), "stdout", "-l", "eng",
        "--oem", "1", "--psm", "3",
    });
    if (!process.waitForFinished(60000)) {
        process.kill();
        return {};
    }
    if (process.exitStatus() == QProcess::CrashExit || process.exitCode() != 0) {
        return {};
    }
    return QString::fromUtf8(process.readAllStandardOutput()).trimmed();
}
}

bool PdfExtractor::isPasswordRequired(const QString &pdfPath) {
    if (pdfPath.isEmpty() || !QFileInfo::exists(pdfPath)) return false;
    QPdfDocument document;
    auto err = document.load(pdfPath);
    return err == QPdfDocument::Error::IncorrectPassword || err == QPdfDocument::Error::UnsupportedSecurityScheme;
}

bool PdfExtractor::verifyPassword(const QString &pdfPath, const QString &password) {
    if (pdfPath.isEmpty() || !QFileInfo::exists(pdfPath)) return false;
    QPdfDocument document;
    if (!password.isEmpty()) {
        document.setPassword(password);
    }
    auto err = document.load(pdfPath);
    return err == QPdfDocument::Error::None;
}

QList<PageLayoutData> PdfExtractor::extractLayouts(const QString &pdfPath, const QString &password) {
    const QString scriptPath = QDir(resourceDirectory()).filePath("extract_pdf.py");
    if (!QFileInfo::exists(scriptPath)) return {};
    QProcess process;
    QProcessEnvironment env = QProcessEnvironment::systemEnvironment();
    env.insert("PYTHONIOENCODING", "utf-8");
    env.insert("PYTHONUTF8", "1");
    process.setProcessEnvironment(env);
    QStringList args = {scriptPath, "--json"};
    if (!password.isEmpty()) {
        args << "--password" << password;
    }
    args << pdfPath;
    process.start(pythonExecutable(), args);
    if (!process.waitForFinished(300000)) {
        process.kill();
        return {};
    }
    if (process.exitStatus() == QProcess::CrashExit || process.exitCode() != 0) {
        return {};
    }

    QByteArray rawOutput = process.readAllStandardOutput().trimmed();
    int jsonStart = rawOutput.indexOf('{');
    int jsonEnd = rawOutput.lastIndexOf('}');
    if (jsonStart != -1 && jsonEnd != -1 && jsonEnd > jsonStart) {
        rawOutput = rawOutput.mid(jsonStart, jsonEnd - jsonStart + 1);
    }
    const QJsonDocument output = QJsonDocument::fromJson(rawOutput);
    if (!output.isObject()) return {};
    const QJsonArray pages = output.object().value("pages").toArray();
    QList<PageLayoutData> result;
    result.reserve(pages.size());

    for (int pIdx = 0; pIdx < pages.size(); ++pIdx) {
        const QJsonValue &pageVal = pages[pIdx];
        PageLayoutData pData;
        pData.pageIndex = pIdx;
        if (pageVal.isObject()) {
            QJsonObject pObj = pageVal.toObject();
            pData.width = pObj.value("width").toDouble(595.0);
            pData.height = pObj.value("height").toDouble(842.0);
            pData.text = pObj.value("text").toString();
            QJsonArray blkArr = pObj.value("blocks").toArray();
            for (const QJsonValue &blkVal : blkArr) {
                QJsonObject blkObj = blkVal.toObject();
                LayoutBlock blk;
                blk.id = blkObj.value("id").toInt();
                QJsonArray bboxArr = blkObj.value("bbox").toArray();
                if (bboxArr.size() >= 4) {
                    qreal x0 = bboxArr[0].toDouble();
                    qreal y0 = bboxArr[1].toDouble();
                    qreal x1 = bboxArr[2].toDouble();
                    qreal y1 = bboxArr[3].toDouble();
                    blk.bbox = QRectF(x0, y0, x1 - x0, y1 - y0);
                }
                blk.text = blkObj.value("text").toString();
                blk.fontSize = blkObj.value("font_size").toDouble(12.0);
                blk.color = QColor(blkObj.value("color").toString("#000000"));
                blk.angle = blkObj.value("angle").toInt(0);
                blk.isHeading = blkObj.value("is_heading").toBool();
                blk.isBold = blkObj.value("is_bold").toBool();
                blk.isWatermark = blkObj.value("is_watermark").toBool();
                pData.blocks.append(blk);
            }
        } else {
            pData.text = pageVal.toString();
        }
        result.append(pData);
    }
    return result;
}

PageLayoutData PdfExtractor::extractPageLayout(const QString &pdfPath, int pageIndex, const QString &password) {
    const QString scriptPath = QDir(resourceDirectory()).filePath("extract_pdf.py");
    if (!QFileInfo::exists(scriptPath)) return {};
    QProcess process;
    QProcessEnvironment env = QProcessEnvironment::systemEnvironment();
    env.insert("PYTHONIOENCODING", "utf-8");
    env.insert("PYTHONUTF8", "1");
    process.setProcessEnvironment(env);
    QStringList args = {scriptPath, "--json", "--page", QString::number(pageIndex)};
    if (!password.isEmpty()) {
        args << "--password" << password;
    }
    args << pdfPath;
    process.start(pythonExecutable(), args);
    if (!process.waitForFinished(60000)) {
        process.kill();
        return {};
    }
    if (process.exitStatus() == QProcess::CrashExit || process.exitCode() != 0) {
        return {};
    }

    QByteArray rawOutput = process.readAllStandardOutput().trimmed();
    int jsonStart = rawOutput.indexOf('{');
    int jsonEnd = rawOutput.lastIndexOf('}');
    if (jsonStart != -1 && jsonEnd != -1 && jsonEnd > jsonStart) {
        rawOutput = rawOutput.mid(jsonStart, jsonEnd - jsonStart + 1);
    }
    const QJsonDocument output = QJsonDocument::fromJson(rawOutput);
    if (!output.isObject()) return {};
    const QJsonArray pages = output.object().value("pages").toArray();
    if (pages.isEmpty()) return {};

    const QJsonObject pObj = pages[0].toObject();
    PageLayoutData pData;
    pData.pageIndex = pageIndex - 1;
    pData.width = pObj.value("width").toDouble(595.0);
    pData.height = pObj.value("height").toDouble(842.0);
    pData.text = pObj.value("text").toString();
    QJsonArray blkArr = pObj.value("blocks").toArray();
    for (const QJsonValue &blkVal : blkArr) {
        QJsonObject blkObj = blkVal.toObject();
        LayoutBlock blk;
        blk.id = blkObj.value("id").toInt();
        QJsonArray bboxArr = blkObj.value("bbox").toArray();
        if (bboxArr.size() >= 4) {
            qreal x0 = bboxArr[0].toDouble();
            qreal y0 = bboxArr[1].toDouble();
            qreal x1 = bboxArr[2].toDouble();
            qreal y1 = bboxArr[3].toDouble();
            blk.bbox = QRectF(x0, y0, x1 - x0, y1 - y0);
        }
        blk.text = blkObj.value("text").toString();
        blk.fontSize = blkObj.value("font_size").toDouble(12.0);
        blk.color = QColor(blkObj.value("color").toString("#000000"));
        blk.angle = blkObj.value("angle").toInt(0);
        blk.isHeading = blkObj.value("is_heading").toBool();
        blk.isBold = blkObj.value("is_bold").toBool();
        blk.isWatermark = blkObj.value("is_watermark").toBool();
        pData.blocks.append(blk);
    }
    return pData;
}

QStringList PdfExtractor::extractPages(const QString &pdfPath, const QString &password) {
    QList<PageLayoutData> layouts = extractLayouts(pdfPath, password);
    QStringList result;
    result.reserve(layouts.size());
    for (const auto &layout : layouts) {
        result.append(layout.text);
    }
    return result;
}

QString PdfExtractor::extractText(const QString &pdfPath, const QString &password) {
    const QStringList pages = extractPages(pdfPath, password);
    QStringList markedPages;
    markedPages.reserve(pages.size());
    for (int index = 0; index < pages.size(); ++index) {
        markedPages.append(pages[index] +
                           QString("\n\n— TRANG %1 —").arg(index + 1));
    }
    return markedPages.join("\n\n");
}

QString PdfExtractor::extractHtml(const QString &) {
    return {};
}

QImage PdfExtractor::renderPageImage(const QString &pdfPath, int pageIndex,
                                     qreal scale, const QString &password) {
    if (pageIndex < 0 || pdfPath.isEmpty()) return {};
    QPdfDocument document;
    if (!password.isEmpty()) {
        document.setPassword(password);
    }
    if (static_cast<int>(document.load(pdfPath)) != 0
            || pageIndex >= document.pageCount()) {
        return {};
    }
    const QSizeF points = pagePointSize(document, pageIndex);
    const QSize target(qMax(1, qRound(points.width() * scale)),
                       qMax(1, qRound(points.height() * scale)));
    return document.render(pageIndex, target);
}
