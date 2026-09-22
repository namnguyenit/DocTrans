#pragma once

#include <QObject>
#include <QString>
#include <QProcess>
#include <QTimer>
#include <QPair>

class OfflineTranslator : public QObject {
    Q_OBJECT
public:
    enum class ModelStatus {
        NotStarted,
        Loading,
        Ready,
        Crashed,
        Stopped
    };
    Q_ENUM(ModelStatus)

signals:
    void nmtReady();
    void polishModelReady();
    void translationResultReady(int reqId, const QString &result);
    void translationPolishedReady(int reqId, const QString &result);
    void translationFailed(int reqId, const QString &error);
    void nmtProcessFailed(const QString &error);
    void modelStatusChanged();

public:
    explicit OfflineTranslator(QObject *parent = nullptr);
    ~OfflineTranslator();

    void requestAsyncTranslation(int reqId, const QString &sentence);
    void requestPolishOnlyAsync(int reqId, const QString &sourceEn, const QString &rawVi);
    void cancelQueuedTranslations();
    void clearCache();
    void restartDaemon();
    void restartPolishModel();

    bool isNmtReady() const { return m_nmtReady; }
    bool isNmtInitialized() const { return m_nmtInitialized; }
    bool isPolishAvailable() const { return m_polishAvailable; }
    QString polishModelName() const { return m_polishModelName; }

    ModelStatus nmtStatus() const { return m_nmtStatus; }
    ModelStatus polishStatus() const { return m_polishStatus; }
    bool isAnyModelCrashed() const {
        return m_nmtStatus == ModelStatus::Crashed || m_polishStatus == ModelStatus::Crashed;
    }
    QString nmtError() const { return m_nmtError; }
    QString polishError() const { return m_polishError; }

private:
    void initNmtDaemon();
    void queryNmtModelAsync(int reqId, const QString &text);
    QString postProcessTranslation(const QString &raw);

    QProcess *m_nmtProcess = nullptr;
    bool      m_nmtReady = false;
    bool      m_nmtInitialized = false;
    bool      m_polishAvailable = false;
    QString   m_polishModelName;

    ModelStatus m_nmtStatus = ModelStatus::Loading;
    ModelStatus m_polishStatus = ModelStatus::Loading;
    QString     m_nmtError;
    QString     m_polishError;

    QTimer m_batchTimer;
    QList<QPair<int, QString>> m_translationQueue;

    static constexpr int kPreferredBatchSize = 32;  // Match Python RESPONSE_GROUP_SIZE

private slots:
    void onNmtOutputReady();
    void flushTranslationQueue();
};
