#include "readDoc/MainWindow.h"
#include <QApplication>
#include <QElapsedTimer>
#include <QFile>
#include <QJsonDocument>
#include <QJsonObject>
#include <QSet>
#include <QTemporaryDir>
#include <QTimer>
#include <QSpinBox>
#include <algorithm>

// Explicit manual stress test: the input PDF is never modified or uploaded.
int main(int argc, char **argv) {
    QApplication app(argc, argv);
    const auto args = app.arguments();
    auto option = [&](const QString &key, const QString &fallback) {
        const int i = args.indexOf(key);
        return i >= 0 && i + 1 < args.size() ? args[i + 1] : fallback;
    };
    const QString input = option("--input", {}), output = option("--report", {});
    if (input.isEmpty() || output.isEmpty()) return 2;
    const int budget = option("--requests", "512").toInt(); // 0 = finish whole document
    const int timeout = option("--seconds", "300").toInt();
    QTemporaryDir temporary;
    qputenv("READDOC_CACHE_DB", (temporary.path() + "/translation.sqlite3").toUtf8());
    MainWindow window;
    window.resize(1440, 900);
    window.show();
    auto *translator = window.findChild<OfflineTranslator *>();
    QSet<int> raw, polished;
    int duplicates = 0, total = 0, rawDone = 0, finalDone = 0, failures = 0;
    QElapsedTimer wall, heartbeat;
    wall.start(); heartbeat.start();
    qint64 longestGap = 0, readyMs = -1;
    QVector<qint64> gaps;
    QPointer<SplitViewReader> reader;
    int navigation = 0;
    qint64 diagnosticMs = 0;
    const QVector<int> pages = {30, 250, 521, 700, 861};
    QObject::connect(translator, &OfflineTranslator::translationResultReady, &app, [&](int id, const QString &) {
        if (raw.contains(id)) ++duplicates;
        raw.insert(id);
    });
    QObject::connect(translator, &OfflineTranslator::translationPolishedReady, &app, [&](int id, const QString &) {
        if (polished.contains(id)) ++duplicates;
        polished.insert(id);
    });
    auto finish = [&](const QString &reason) {
        std::sort(gaps.begin(), gaps.end());
        QJsonObject report;
        report["reason"] = reason;
        report["source_pages"] = reader ? reader->findChild<QSpinBox *>()->maximum() : 0;
        report["units_total"] = total;
        report["raw_units_done"] = rawDone;
        report["final_units_done"] = finalDone;
        report["raw_requests"] = raw.size();
        report["polish_responses"] = polished.size();
        report["duplicate_responses"] = duplicates;
        report["failures"] = failures;
        report["ready_seconds"] = readyMs / 1000.0;
        report["wall_seconds"] = wall.elapsed() / 1000.0;
        report["translation_seconds"] = readyMs >= 0 ? (wall.elapsed() - readyMs) / 1000.0 : 0;
        report["event_loop_max_gap_ms"] = longestGap;
        report["event_loop_p95_gap_ms"] = gaps.isEmpty() ? 0 : gaps[qMin(gaps.size() - 1, gaps.size() * 95 / 100)];
        report["navigation_checks"] = navigation;
        report["complete"] = reader && reader->isTranslationComplete();
        report["model"] = translator->polishModelName();
        report["nmt_ready"] = translator->isNmtReady();
        report["polish_ready"] = translator->isPolishAvailable();
        report["last_model_diagnostics"] = translator->modelDiagnostics();
        QFile file(output);
        if (!file.open(QIODevice::WriteOnly)) { app.exit(3); return; }
        file.write(QJsonDocument(report).toJson());
        const QString screenshot = option("--screenshot", {});
        if (!screenshot.isEmpty()) window.grab().save(screenshot);
        if (reader) reader->stopTranslation();
        const bool expectedEnd = reason == "complete" || reason == "request_budget";
        const bool modelsOk = !qEnvironmentVariableIsSet("READDOC_STRESS_REQUIRE_CUDA") ||
            (translator->isNmtReady() && translator->isPolishAvailable() &&
             translator->polishModelName().contains("CUDA"));
        app.exit(failures || duplicates || readyMs < 0 || !expectedEnd || !modelsOk ? 1 : 0);
    };
    QTimer timer;
    timer.setInterval(25);
    QObject::connect(&timer, &QTimer::timeout, &app, [&]() {
        const qint64 gap = heartbeat.restart();
        longestGap = qMax(longestGap, gap);
        gaps.append(gap);
        if (wall.elapsed() - diagnosticMs >= 5000) {
            diagnosticMs = wall.elapsed();
            translator->requestModelDiagnostics();
            QJsonObject progress;
            progress["elapsed_seconds"] = wall.elapsed() / 1000.0;
            progress["polish_responses"] = polished.size();
            progress["raw_requests"] = raw.size();
            progress["last_model_diagnostics"] = translator->modelDiagnostics();
            QFile snapshot(output + ".progress.json");
            if (snapshot.open(QIODevice::WriteOnly)) snapshot.write(QJsonDocument(progress).toJson());
        }
        if (!reader) {
            reader = window.findChild<SplitViewReader *>();
            if (reader) {
                readyMs = wall.elapsed();
                QObject::connect(reader, &SplitViewReader::progressChanged, &app,
                    [&](int a, int b, int count, bool, int failed) { rawDone = a; finalDone = b; total = count; failures = failed; });
            }
        }
        if (reader && navigation < pages.size() && polished.size() >= (navigation + 1) * 80) {
            const int page = pages[navigation++];
            reader->goToPage(page);
            const QString screenshot = option("--screenshot", {});
            if (page == 521 && !screenshot.isEmpty())
                window.grab().save(screenshot + ".page521.png");
        }
        if (reader && (reader->isTranslationComplete() || (budget > 0 && polished.size() >= budget))) {
            finish(reader->isTranslationComplete() ? "complete" : "request_budget");
        } else if (wall.elapsed() >= timeout * 1000LL) finish("time_budget");
    });
    timer.start();
    window.openDocuments({input});
    return app.exec();
}
