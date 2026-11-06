#pragma once

#include <QHash>
#include <QList>
#include <QMap>
#include <QString>

struct TranslationRequest {
    int id = 0;
    int client = 0;
    QString text;
    QString raw;
    bool polishOnly = false;
    QString context;
};

// One bounded window for both stages, shared by every open document.
// Credits return after polish, not after the faster raw translation stage.
class TranslationScheduler {
public:
    explicit TranslationScheduler(int capacity = 96) : m_capacity(capacity) {}
    int nextRequestId() { return ++m_requestId; }
    int newClient() { return ++m_clientId; }
    void enqueue(const TranslationRequest &request) {
        if (!m_queues.contains(request.client)) m_order.append(request.client);
        m_queues[request.client].append(request);
    }
    QList<TranslationRequest> takeBatch(int limit) {
        QList<TranslationRequest> batch;
        while (!m_order.isEmpty() && batch.size() < limit && m_active.size() < m_capacity) {
            const int client = m_order.takeFirst();
            auto &queue = m_queues[client];
            auto request = queue.takeFirst();
            if (queue.isEmpty()) m_queues.remove(client);
            else m_order.append(client);
            m_active.insert(request.id, request);
            batch.append(request);
        }
        return batch;
    }
    void finish(int id) { m_active.remove(id); }
    QList<int> cancelClient(int client) {
        m_queues.remove(client);
        m_order.removeAll(client);
        QList<int> ids;
        for (const auto &request : m_active)
            if (request.client == client) ids.append(request.id);
        // Keep active credits until the daemon acknowledges cancellation.
        return ids;
    }
    QList<int> abortAll() {
        QList<int> ids = m_active.keys();
        for (const auto &queue : m_queues)
            for (const auto &request : queue) ids.append(request.id);
        m_queues.clear();
        m_order.clear();
        m_active.clear();
        return ids;
    }
    int activeCount() const { return m_active.size(); }
    int queuedCount() const {
        int count = 0;
        for (const auto &queue : m_queues) count += queue.size();
        return count;
    }
private:
    int m_capacity;
    int m_requestId = 0;
    int m_clientId = 0;
    QMap<int, QList<TranslationRequest>> m_queues;
    QList<int> m_order;
    QHash<int, TranslationRequest> m_active;
};
