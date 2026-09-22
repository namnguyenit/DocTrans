#include "readDoc/Data/PdfExtractor.h"

#include <QDir>
#include <QCoreApplication>
#include <QFileInfo>
#include <QJsonArray>
#include <QJsonDocument>
#include <QJsonObject>
#include <QProcess>
#include <QRegularExpression>

#import <AppKit/AppKit.h>
#import <PDFKit/PDFKit.h>
#import <Vision/Vision.h>

namespace {
QString extractorScriptPath() {
    const QString configured = qEnvironmentVariable("READDOC_RESOURCE_DIR");
    if (!configured.isEmpty()) {
        const QString script = QDir(configured).filePath("extract_pdf.py");
        if (QFileInfo::exists(script)) return script;
    }
    const QString bundled = QDir(QCoreApplication::applicationDirPath())
        .absoluteFilePath("../Resources/extract_pdf.py");
    if (QFileInfo::exists(bundled)) return bundled;
    return QDir::current().absoluteFilePath("src/Data/extract_pdf.py");
}

QString pythonExecutable() {
    const QString configured = qEnvironmentVariable("READDOC_PYTHON");
    if (!configured.isEmpty() && QFileInfo::exists(configured)) return configured;
    return QFileInfo::exists("/opt/homebrew/bin/python3")
        ? "/opt/homebrew/bin/python3" : "python3";
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

QString recognizePageLocally(PDFPage *page) {
    if (!page) return {};
    NSRect bounds = [page boundsForBox:kPDFDisplayBoxCropBox];
    const CGFloat maxDimension = 2200.0;
    const CGFloat scale = qMin<CGFloat>(3.0, maxDimension /
        qMax<CGFloat>(1.0, qMax(bounds.size.width, bounds.size.height)));
    NSImage *thumbnail = [page thumbnailOfSize:NSMakeSize(
        qMax<CGFloat>(1.0, bounds.size.width * scale),
        qMax<CGFloat>(1.0, bounds.size.height * scale))
                                         forBox:kPDFDisplayBoxCropBox];
    CGImageRef cgImage = [thumbnail CGImageForProposedRect:nullptr context:nil hints:nil];
    if (!cgImage) return {};

    VNRecognizeTextRequest *request = [[VNRecognizeTextRequest alloc] init];
    request.recognitionLevel = VNRequestTextRecognitionLevelAccurate;
    request.usesLanguageCorrection = YES;
    request.recognitionLanguages = @[@"en-US"];
    request.minimumTextHeight = 0.006;
    VNImageRequestHandler *handler = [[VNImageRequestHandler alloc]
        initWithCGImage:cgImage options:@{}];
    NSError *error = nil;
    if (![handler performRequests:@[request] error:&error] || error) return {};

    NSArray<VNRecognizedTextObservation *> *observations = request.results;
    observations = [observations sortedArrayUsingComparator:
        ^NSComparisonResult(VNRecognizedTextObservation *left,
                            VNRecognizedTextObservation *right) {
        const CGFloat leftY = CGRectGetMaxY(left.boundingBox);
        const CGFloat rightY = CGRectGetMaxY(right.boundingBox);
        if (qAbs(leftY - rightY) > 0.012) {
            return leftY > rightY ? NSOrderedAscending : NSOrderedDescending;
        }
        return CGRectGetMinX(left.boundingBox) < CGRectGetMinX(right.boundingBox)
            ? NSOrderedAscending : NSOrderedDescending;
    }];

    QStringList lines;
    for (VNRecognizedTextObservation *observation in observations) {
        VNRecognizedText *candidate = [[observation topCandidates:1] firstObject];
        if (!candidate || candidate.confidence < 0.20 || candidate.string.length == 0) {
            continue;
        }
        lines.append(QString::fromNSString(candidate.string).trimmed());
    }
    lines.removeAll(QString());
    return lines.join("\n\n");
}
}

bool PdfExtractor::isPasswordRequired(const QString &pdfPath) {
    if (pdfPath.isEmpty() || !QFileInfo::exists(pdfPath)) return false;
    @autoreleasepool {
        PDFDocument *pdf = [[PDFDocument alloc]
            initWithURL:[NSURL fileURLWithPath:pdfPath.toNSString()]];
        return pdf && [pdf isLocked];
    }
}

bool PdfExtractor::verifyPassword(const QString &pdfPath, const QString &password) {
    if (pdfPath.isEmpty() || !QFileInfo::exists(pdfPath)) return false;
    @autoreleasepool {
        PDFDocument *pdf = [[PDFDocument alloc]
            initWithURL:[NSURL fileURLWithPath:pdfPath.toNSString()]];
        if (!pdf) return false;
        if (![pdf isLocked]) return true;
        return [pdf unlockWithPassword:password.toNSString()];
    }
}

QList<PageLayoutData> PdfExtractor::extractLayouts(const QString &pdfPath, const QString &password) {
    QProcess process;
    QStringList args;
    args << extractorScriptPath() << "--json";
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
    QProcess process;
    QStringList args;
    args << extractorScriptPath() << "--json" << "--page" << QString::number(pageIndex);
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
    QProcess process;
    QStringList args;
    args << extractorScriptPath() << "--json";
    if (!password.isEmpty()) {
        args << "--password" << password;
    }
    args << pdfPath;
    process.start(pythonExecutable(), args);
    if (!process.waitForFinished(90000)) {
        process.kill();
        return {};
    }
    if (process.exitStatus() == QProcess::CrashExit || process.exitCode() != 0) {
        return {};
    }

    QJsonDocument document = QJsonDocument::fromJson(process.readAllStandardOutput());
    if (!document.isObject()) return {};
    QJsonArray pages = document.object().value("pages").toArray();
    QStringList result;
    result.reserve(pages.size());
    for (const QJsonValue &page : pages) result.append(page.toString());

    @autoreleasepool {
        PDFDocument *pdf = [[PDFDocument alloc]
            initWithURL:[NSURL fileURLWithPath:pdfPath.toNSString()]];
        if (pdf && [pdf isLocked] && !password.isEmpty()) {
            [pdf unlockWithPassword:password.toNSString()];
        }
        const int count = qMin(result.size(), static_cast<int>(pdf.pageCount));
        for (int index = 0; index < count; ++index) {
            if (!needsLocalOcr(result[index])) continue;
            const QString recognized = recognizePageLocally(
                [pdf pageAtIndex:static_cast<NSUInteger>(index)]);
            if (!recognized.isEmpty()) {
                if (!result[index].isEmpty()) result[index].append("\n\n");
                result[index].append(recognized);
            }
        }
    }
    return result;
}

QString PdfExtractor::extractText(const QString &pdfPath, const QString &password) {
    QStringList pages = extractPages(pdfPath, password);
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

    @autoreleasepool {
        PDFDocument *document = [[PDFDocument alloc]
            initWithURL:[NSURL fileURLWithPath:pdfPath.toNSString()]];
        if (!document) return {};
        if ([document isLocked] && !password.isEmpty()) {
            [document unlockWithPassword:password.toNSString()];
        }
        if ([document isLocked] || pageIndex >= static_cast<int>(document.pageCount)) return {};

        PDFPage *page = [document pageAtIndex:static_cast<NSUInteger>(pageIndex)];
        if (!page) return {};
        NSRect bounds = [page boundsForBox:kPDFDisplayBoxCropBox];
        NSSize targetSize = NSMakeSize(qMax<qreal>(1.0, bounds.size.width * scale),
                                       qMax<qreal>(1.0, bounds.size.height * scale));
        NSImage *thumbnail = [page thumbnailOfSize:targetSize
                                            forBox:kPDFDisplayBoxCropBox];
        if (!thumbnail) return {};

        CGImageRef cgImage = [thumbnail CGImageForProposedRect:nullptr
                                                       context:nil
                                                         hints:nil];
        if (!cgImage) return {};
        NSBitmapImageRep *bitmap = [[NSBitmapImageRep alloc] initWithCGImage:cgImage];
        NSData *png = [bitmap representationUsingType:NSBitmapImageFileTypePNG
                                           properties:@{}];
        if (!png) return {};
        return QImage::fromData(static_cast<const uchar *>(png.bytes),
                                static_cast<int>(png.length), "PNG");
    }
}
