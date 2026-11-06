#include "readDoc/MainWindow.h"
#include <QApplication>
#include <QDir>
#include <QFile>
#include <QPdfDocument>
#include <QPdfSelection>
#include <QPdfWriter>
#include <QPainter>
#include <QTemporaryDir>
#include <QTimer>
#include <QDebug>
#include <QElapsedTimer>
#include <QJsonDocument>
#include <QJsonObject>

static void check(bool condition, const char *message) {
    if (!condition) qFatal("%s", message);
}

int main(int argc, char **argv) {
    QApplication app(argc, argv);
    app.setApplicationName("readDoc-test");
    QTemporaryDir temp;
    check(temp.isValid(), "temporary workspace");
    const bool realModel = app.arguments().contains("--real-model");
    qputenv("READDOC_CACHE_DB", QDir(temp.path()).filePath("translation.sqlite3").toUtf8());
    auto write = [&](const QString &name, const QString &text) {
        const QString path = QDir(temp.path()).filePath(name);
        QFile file(path);
        check(file.open(QIODevice::WriteOnly), "create synthetic input");
        file.write(text.toUtf8());
        return path;
    };
    const QString alpha = write("alpha.txt", "DOCUMENT_ALPHA The driver allocates a buffer before starting the DMA transfer.\n\nRestart the service after updating the configuration file.");
    const QString beta = write("beta.md", "# DOCUMENT_BETA\n\nThe kernel checks access permissions before mapping physical memory.\n\nUse separate queues to avoid blocking unrelated requests.");
    const QString pdfPath = QDir(temp.path()).filePath("gamma.pdf");
    {
        QPdfWriter writer(pdfPath);
        QPainter painter(&writer);
        painter.setFont(QFont("Arial", 14));
        painter.drawText(QRect(500, 500, 8000, 4000), Qt::TextWordWrap,
                         "DOCUMENT_GAMMA Verify pending writes before disconnecting the storage device.");
    }
    MainWindow window;
    auto *translator = window.findChild<OfflineTranslator *>();
    QSet<int> rawIds, polishedIds;
    int survivingRawCount = 0;
    QObject::connect(translator, &OfflineTranslator::translationResultReady, &app,
                     [&](int id, const QString &text) {
                         rawIds.insert(id);
                         if (text.contains("SURVIVING_DOCUMENT_BETA")) ++survivingRawCount;
                     });
    QObject::connect(translator, &OfflineTranslator::translationPolishedReady, &app,
                     [&](int id, const QString &) { polishedIds.insert(id); });
    window.resize(1440, 900);
    window.show();
    window.openDocuments({alpha, beta, pdfPath});
    auto *tabs = window.findChild<QTabWidget *>();
    check(tabs != nullptr, "multi-document tabs");
    check(tabs->count() == 3, "three documents are queued together");
    window.openDocuments({alpha});
    check(tabs->count() == 3, "duplicate file does not create duplicate translation work");
    QTimer timer;
    timer.setInterval(25);
    int phase = 0;
    int pausedTicks = 0;
    int completeTicks = 0;
    int initialRawCount = 0;
    QElapsedTimer sustained;
    QPointer<SplitViewReader> paused;
    QObject::connect(&timer, &QTimer::timeout, &app, [&]() {
        auto reader = [&](int tab) -> SplitViewReader * {
            auto *page = tabs->widget(tab);
            return page ? page->findChild<SplitViewReader *>() : nullptr;
        };
        auto allComplete = [&]() {
            for (int i = 0; i < tabs->count(); ++i)
                if (!reader(i) || !reader(i)->isTranslationComplete()) return false;
            return true;
        };
        if (phase == 0) {
            if (!allComplete()) return;
            if (++completeTicks < 6) return;  // Allow the throttled progress display to repaint.
            for (int i = 0; i < 3; ++i) {
                const QString output = QDir(temp.path()).filePath(QString("result_%1.pdf").arg(i));
                QString error;
                check(reader(i)->exportToPdf(output, &error), qPrintable(error));
                QPdfDocument document;
                check(document.load(output) == QPdfDocument::Error::None && document.pageCount() > 0,
                      "completed document exports a readable PDF");
                if (i < 2 && !realModel) {
                    QString text;
                    for (int page = 0; page < document.pageCount(); ++page) text += document.getAllText(page).text();
                    check(text.contains("VI_RESULT"), "text export must contain translations, not source text");
                    if (i == 1) check(text.contains("VI_RESULT: Use separate queues"), "normal prose containing avoid must be translated");
                    check(text.contains(i == 0 ? "DOCUMENT_ALPHA" : "DOCUMENT_BETA"), "translation routed to correct document");
                    check(!text.contains(i == 0 ? "DOCUMENT_BETA" : "DOCUMENT_ALPHA"), "no cross-document result contamination");
                }
            }
            tabs->setCurrentIndex(0);
            const QString screenshot = qEnvironmentVariable("READDOC_TEST_SCREENSHOT");
            if (!screenshot.isEmpty()) window.grab().save(screenshot);
            if (realModel) {
                check(translator->isNmtReady() && translator->isPolishAvailable(), "both real models must be available");
                QStringList more;
                for (int doc = 0; doc < 4; ++doc) {
                    QStringList blocks;
                    for (int unit = 0; unit < 32; ++unit)
                        blocks.append(QString("File %1, paragraph %2. The driver checks the buffer before starting the DMA transfer.").arg(doc + 1).arg(unit + 1));
                    more.append(write(QString("sustained_%1.txt").arg(doc), blocks.join("\n\n")));
                }
                sustained.start();
                initialRawCount = rawIds.size();
                window.openDocuments(more);
                completeTicks = 0;
                phase = 10;
                return;
            }
            QStringList manyA, manyB;
            for (int i = 0; i < 360; ++i) {
                manyA.append(QString("CANCELLED_DOCUMENT_ALPHA Request number %1 must remain isolated.").arg(i));
                manyB.append(QString("SURVIVING_DOCUMENT_BETA Keep translating request number %1.").arg(i));
            }
            window.openDocuments({write("cancel_me.txt", manyA.join("\n\n")),
                                  write("keep_me.txt", manyB.join("\n\n"))});
            phase = 1;
        } else if (phase == 1) {
            if (!reader(3) || !reader(4)) return;
            for (int i = 0; i < 20; ++i) {
                tabs->setCurrentIndex(3);
                tabs->setCurrentIndex(4);
            }
            tabs->tabCloseRequested(3);
            check(tabs->count() == 4, "closing one background document removes only that tab");
            phase = 2;
        } else if (phase == 2) {
            if (!allComplete()) return;
            check(survivingRawCount == 360, "switching tabs must not duplicate in-flight translation units");
            window.openDocuments({write("pause_me.txt", QString("PAUSABLE_DOCUMENT Restart the service after updating the configuration.\n\n").repeated(90))});
            phase = 3;
        } else if (phase == 3) {
            paused = reader(4);
            if (!paused) return;
            paused->stopTranslation();
            tabs->setCurrentIndex(0);
            tabs->setCurrentIndex(4);
            check(!paused->isTranslationComplete(), "switching tabs must not silently resume a paused document");
            phase = 4;
        } else if (phase == 4) {
            if (++pausedTicks < 5) return;
            check(QMetaObject::invokeMethod(paused, "resumeOrRestartModels", Qt::DirectConnection), "resume current document");
            phase = 5;
        } else if (phase == 5) {
            if (!allComplete()) return;
            window.openDocuments({write("bad.txt", "FAIL_MODEL This document has a synthetic model failure."),
                                  write("healthy.txt", "HEALTHY_DOCUMENT This document must still finish normally.")});
            phase = 6;
        } else if (phase == 6) {
            if (!reader(5) || !reader(6) || !reader(6)->isTranslationComplete()) return;
            check(!reader(5)->isTranslationComplete(), "failed document cannot be reported as complete");
            QString error;
            check(!reader(5)->exportToPdf(QDir(temp.path()).filePath("incomplete.pdf"), &error), "prevent incomplete export");
            qInfo() << "Multi-document integration checks passed: route, export, duplicate, close, pause/resume, failure isolation";
            app.exit(0);
        } else if (phase == 10) {
            if (!allComplete() || ++completeTicks < 6) return;
            check(rawIds == polishedIds && rawIds.size() >= 128, "all real raw requests must finish polish");
            check(rawIds.size() - initialRawCount == 128, "sustained multi-document workload must not send duplicate GPU work");
            const QString reportPath = qEnvironmentVariable("READDOC_TEST_REPORT");
            if (!reportPath.isEmpty()) {
                QFile report(reportPath);
                check(report.open(QIODevice::WriteOnly), "write actual GPU integration evidence");
                QJsonObject result;
                result["documents_completed"] = tabs->count();
                result["raw_responses"] = rawIds.size();
                result["polish_responses"] = polishedIds.size();
                result["sustained_documents"] = 4;
                result["sustained_units"] = 128;
                result["sustained_raw_requests"] = rawIds.size() - initialRawCount;
                result["sustained_seconds_including_parsing"] = sustained.elapsed() / 1000.0;
                result["polish_model"] = translator->polishModelName();
                result["initial_three_documents_exported"] = true;
                report.write(QJsonDocument(result).toJson());
            }
            tabs->setCurrentIndex(tabs->count() - 1);
            const QString screenshot = qEnvironmentVariable("READDOC_TEST_SCREENSHOT");
            if (!screenshot.isEmpty()) window.grab().save(screenshot);
            app.exit(0);
        }
    });
    timer.start();
    QTimer::singleShot(realModel ? 240000 : 40000, &app, [&]() { qCritical() << "Multi-document test timed out in phase" << phase; app.exit(1); });
    return app.exec();
}
