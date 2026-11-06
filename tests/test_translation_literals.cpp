#include "readDoc/System/OfflineTranslator.h"
#include <QCoreApplication>
#include <QHash>
#include <QSet>
#include <QTemporaryDir>
#include <QTimer>

int main(int argc, char **argv) {
    QCoreApplication app(argc, argv);
    QTemporaryDir temporary;
    qputenv("READDOC_CACHE_DB", (temporary.path() + "/cache.sqlite3").toUtf8());
    qputenv("READDOC_TEST_VERBATIM", "1");
    QHash<int, QString> expected;
    QSet<int> rawIds, finalIds;
    OfflineTranslator translator;
    auto receive = [&](int id, const QString &text, bool final) {
        if (expected.value(id) != text) qFatal("Translation transport altered a validated technical literal");
        (final ? finalIds : rawIds).insert(id);
        if (rawIds.size() == expected.size() && finalIds.size() == expected.size()) app.exit(0);
    };
    QObject::connect(&translator, &OfflineTranslator::translationResultReady, &app,
        [&](int id, const QString &text) { receive(id, text, false); });
    QObject::connect(&translator, &OfflineTranslator::translationPolishedReady, &app,
        [&](int id, const QString &text) { receive(id, text, true); });
    QObject::connect(&translator, &OfflineTranslator::nmtReady, &app, [&] {
        if (!expected.isEmpty()) return;
        const QStringList cases = {"gpio_cfg converts 16 / 8 bytes.", "i2c_cfg: __IRQ0__ / __IRQ1__",
            "`a  /  b` keeps internal spacing.", "first line\nsecond line"};
        for (const auto &text : cases) {
            const int id = translator.allocateRequestId();
            expected.insert(id, text);
            translator.requestAsyncTranslation(id, text);
        }
    });
    QTimer::singleShot(8000, &app, [&] { qFatal("Literal transport test timed out"); });
    return app.exec();
}
