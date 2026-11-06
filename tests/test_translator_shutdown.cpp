#include "readDoc/System/OfflineTranslator.h"
#include <QCoreApplication>
#include <QTemporaryDir>
#include <QTimer>

int main(int argc, char **argv) {
    QCoreApplication app(argc, argv);
    QTemporaryDir temporary;
    qputenv("READDOC_CACHE_DB", (temporary.path() + "/cache.sqlite3").toUtf8());
    auto *translator = new OfflineTranslator;
    bool destroying = false, started = false;
    auto noShutdownSignal = [&] {
        if (destroying) qFatal("Intentional shutdown emitted a callback into a closing reader");
    };
    QObject::connect(translator, &OfflineTranslator::translationFailed, &app, noShutdownSignal);
    QObject::connect(translator, &OfflineTranslator::modelStatusChanged, &app, noShutdownSignal);
    QObject::connect(translator, &OfflineTranslator::nmtReady, &app, [&] {
        if (started) return;
        started = true;
        const int client = translator->registerClient();
        for (int i = 0; i < 500; ++i)
            translator->requestAsyncTranslation(translator->allocateRequestId(),
                QString("Pending request %1 must not become a shutdown failure.").arg(i), client);
        QTimer::singleShot(20, &app, [&] {
            destroying = true;
            delete translator;
            app.exit(0);
        });
    });
    QTimer::singleShot(8000, &app, [&] { qFatal("Shutdown test did not initialize"); });
    return app.exec();
}
