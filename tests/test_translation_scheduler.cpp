#include "readDoc/System/TranslationScheduler.h"
#include <QCoreApplication>
#include <QDebug>

static void check(bool condition, const char *message) {
    if (!condition) qFatal("%s", message);
}

int main(int argc, char **argv) {
    QCoreApplication app(argc, argv);
    TranslationScheduler scheduler(4);
    const int a = scheduler.newClient(), b = scheduler.newClient();
    QList<int> aIds, bIds;
    for (int i = 0; i < 3; ++i) {
        const int id = scheduler.nextRequestId();
        aIds.append(id);
        scheduler.enqueue({id, a, "document A", {}, false, "TCP firewall"});
    }
    for (int i = 0; i < 3; ++i) {
        const int id = scheduler.nextRequestId();
        bIds.append(id);
        scheduler.enqueue({id, b, "document B", {}, false, "Cargo ships"});
    }
    auto batch = scheduler.takeBatch(32);
    check(batch.size() == 4, "bounded active window");
    check(batch[0].client == a && batch[1].client == b && batch[2].client == a && batch[3].client == b,
          "documents must alternate, including different document lengths");
    for (const auto &request : batch)
        check(request.context == (request.client == a ? "TCP firewall" : "Cargo ships"),
              "interleaving must preserve each document's source context");
    check(scheduler.takeBatch(32).isEmpty(), "raw-stage responses must not release polish credits");
    auto cancelled = scheduler.cancelClient(a);
    check(cancelled.size() == 2, "cancel returns active requests for only one document");
    check(scheduler.queuedCount() == 1, "cancel keeps other document pending work");
    check(scheduler.activeCount() == 4, "cancel waits for daemon acknowledgement");
    for (int id : cancelled) scheduler.finish(id);
    batch = scheduler.takeBatch(32);
    check(batch.size() == 1 && batch[0].id == bIds[2], "other document continues after cancellation");
    const int lastId = scheduler.nextRequestId();
    check(lastId > bIds.last(), "request ids are global and never reused across documents");
    check(scheduler.abortAll().size() == 3, "restart releases every remaining active request");
    check(scheduler.activeCount() == 0 && scheduler.queuedCount() == 0, "restart empties scheduling state");
    check(scheduler.nextRequestId() > lastId, "restart must not reuse stale response ids");
    qInfo() << "Translation scheduler checks passed";
    return 0;
}
