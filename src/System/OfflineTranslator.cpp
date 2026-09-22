#include "readDoc/System/OfflineTranslator.h"
#include <QRegularExpression>
#include <QJsonDocument>
#include <QJsonObject>
#include <QJsonArray>
#include <QCoreApplication>
#include <QFileInfo>
#include <QDir>
#include <QDebug>

namespace {
QString resourceDirectory() {
    const QString configured = qEnvironmentVariable("READDOC_RESOURCE_DIR");
    if (!configured.isEmpty() && QDir(configured).exists()) return configured;
    const QDir executableDir{QCoreApplication::applicationDirPath()};
    const QStringList candidates = {
        executableDir.absoluteFilePath("../Resources"),
        executableDir.absoluteFilePath("../share/readDoc"),
        executableDir.absoluteFilePath("resources"),
        QDir::current().absoluteFilePath("src/System"),
    };
    for (const QString &candidate : candidates) {
        if (QFileInfo::exists(QDir(candidate).filePath("local_nmt_daemon.py"))) {
            return QDir(candidate).absolutePath();
        }
    }
    return {};
}

QString pythonExecutable() {
    const QString configured = qEnvironmentVariable("READDOC_PYTHON");
    if (!configured.isEmpty() && QFileInfo::exists(configured)) {
        qDebug() << "Using configured READDOC_PYTHON:" << configured;
        return configured;
    }

    // Traverse upwards from application dir
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
                qDebug() << "Found venv python from app dir:" << candidate;
                return QDir::cleanPath(candidate);
            }
        }
        if (!appDir.cdUp()) break;
    }

    // Traverse upwards from working directory
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
                qDebug() << "Found venv python from work dir:" << candidate;
                return QDir::cleanPath(candidate);
            }
        }
        if (!workDir.cdUp()) break;
    }

#ifdef Q_OS_WIN
    qWarning() << "No project .venv python found, falling back to system python";
    return "python";
#else
    if (QFileInfo::exists("/opt/homebrew/bin/python3")) return "/opt/homebrew/bin/python3";
    if (QFileInfo::exists("/usr/local/bin/python3")) return "/usr/local/bin/python3";
    return "python3";
#endif
}
}

OfflineTranslator::OfflineTranslator(QObject *parent)
    : QObject(parent)
{
    initNmtDaemon();
    
    m_batchTimer.setSingleShot(true);
    connect(&m_batchTimer, &QTimer::timeout, this, &OfflineTranslator::flushTranslationQueue);
}

OfflineTranslator::~OfflineTranslator() {
    if (m_nmtProcess && m_nmtProcess->state() != QProcess::NotRunning) {
        m_nmtProcess->kill();
        m_nmtProcess->waitForFinished(1000);
    }
}

void OfflineTranslator::initNmtDaemon() {
    m_nmtStatus = ModelStatus::Loading;
    m_polishStatus = ModelStatus::Loading;
    m_nmtReady = false;
    m_polishAvailable = false;
    m_nmtInitialized = false;
    m_nmtError.clear();
    m_polishError.clear();

    m_nmtProcess = new QProcess(this);
    QProcessEnvironment env = QProcessEnvironment::systemEnvironment();
    env.insert("KMP_DUPLICATE_LIB_OK", "TRUE");
    env.insert("PYTHONWARNINGS", "ignore");
    env.insert("HF_HUB_DISABLE_SYMLINKS_WARNING", "1");
    env.insert("HF_HUB_OFFLINE", "1");
    env.insert("TRANSFORMERS_OFFLINE", "1");
    env.insert("HF_DATASETS_OFFLINE", "1");
    env.insert("PYTHONIOENCODING", "utf-8");
    env.insert("PYTHONUTF8", "1");
    const QString resources = resourceDirectory();
    const QString modelPath = QDir(resources).filePath("model");
    if (QDir(modelPath).exists() && !env.contains("READDOC_NMT_MODEL")) {
        env.insert("READDOC_NMT_MODEL", modelPath);
    }

    // Search for models root directory
    QDir searchDir(QCoreApplication::applicationDirPath());
    for (int i = 0; i < 7; ++i) {
        if (searchDir.exists("models")) {
            const QString modelsDir = searchDir.absoluteFilePath("models");
            env.insert("READDOC_MODELS_DIR", modelsDir);
            const QString polishFile = QDir(modelsDir).filePath("polish/Arcee-VyLinh.Q6_K.gguf");
            if (QFileInfo::exists(polishFile)) {
                env.insert("READDOC_POLISH_MODEL", polishFile);
            }
            const QString vinaiDir = QDir(modelsDir).filePath("vinai-translate-en2vi");
            if (QFileInfo::exists(QDir(vinaiDir).filePath("config.json"))) {
                env.insert("READDOC_NMT_MODEL", vinaiDir);
            }
            break;
        }
        if (!searchDir.cdUp()) break;
    }

#ifdef READDOC_LINUX
    env.insert("READDOC_NMT_BACKEND", "ctranslate2");
#endif
    m_nmtProcess->setProcessEnvironment(env);

    const QString scriptPath = QDir(resources).filePath("local_nmt_daemon.py");
    if (QFileInfo::exists(scriptPath)) {
        connect(m_nmtProcess, &QProcess::readyReadStandardOutput, this, &OfflineTranslator::onNmtOutputReady);
        connect(m_nmtProcess, &QProcess::readyReadStandardError, this, [this]() {
            qDebug() << "NMT AI Error:" << m_nmtProcess->readAllStandardError();
        });
        connect(m_nmtProcess, &QProcess::errorOccurred, this,
                [this](QProcess::ProcessError) {
            m_nmtReady = false;
            m_polishAvailable = false;
            m_nmtInitialized = true;
            m_nmtStatus = ModelStatus::Crashed;
            m_polishStatus = ModelStatus::Crashed;
            m_nmtError = m_nmtProcess ? m_nmtProcess->errorString() : "Lỗi tiến trình";
            m_polishError = m_nmtError;
            emit nmtProcessFailed(m_nmtError);
            emit modelStatusChanged();
        });
        connect(m_nmtProcess, qOverload<int, QProcess::ExitStatus>(&QProcess::finished), this,
                [this](int exitCode, QProcess::ExitStatus status) {
            if (status == QProcess::CrashExit || exitCode != 0) {
                m_nmtReady = false;
                m_polishAvailable = false;
                m_nmtInitialized = true;
                m_nmtStatus = ModelStatus::Crashed;
                m_polishStatus = ModelStatus::Crashed;
                m_nmtError = QString("Tiến trình model local đã dừng (mã %1)").arg(exitCode);
                m_polishError = m_nmtError;
                emit nmtProcessFailed(m_nmtError);
                emit modelStatusChanged();
            }
        });
        m_nmtProcess->start(
            pythonExecutable(), QStringList() << "-X" << "utf8" << "-W" << "ignore" << scriptPath);
    } else {
        m_nmtInitialized = true;
        m_nmtStatus = ModelStatus::Crashed;
        m_polishStatus = ModelStatus::Crashed;
        m_nmtError = "Không tìm thấy local_nmt_daemon.py";
        emit nmtProcessFailed(m_nmtError);
        emit modelStatusChanged();
    }
}

void OfflineTranslator::restartDaemon() {
    qDebug() << "Restarting OfflineTranslator daemon...";
    cancelQueuedTranslations();
    if (m_nmtProcess) {
        m_nmtProcess->disconnect(this);
        if (m_nmtProcess->state() != QProcess::NotRunning) {
            m_nmtProcess->kill();
            m_nmtProcess->waitForFinished(1000);
        }
        m_nmtProcess->deleteLater();
        m_nmtProcess = nullptr;
    }
    m_nmtReady = false;
    m_polishAvailable = false;
    m_nmtInitialized = false;
    m_nmtStatus = ModelStatus::Loading;
    m_polishStatus = ModelStatus::Loading;
    m_nmtError.clear();
    m_polishError.clear();
    emit modelStatusChanged();
    initNmtDaemon();
}

void OfflineTranslator::restartPolishModel() {
    if (!m_nmtProcess || m_nmtProcess->state() != QProcess::Running) {
        restartDaemon();
        return;
    }
    m_polishStatus = ModelStatus::Loading;
    m_polishAvailable = false;
    m_polishError.clear();
    emit modelStatusChanged();
    QJsonObject req;
    req["action"] = "restart_polish";
    m_nmtProcess->write(QJsonDocument(req).toJson(QJsonDocument::Compact) + "\n");
}

void OfflineTranslator::requestPolishOnlyAsync(int reqId, const QString &sourceEn, const QString &rawVi) {
    if (!m_nmtProcess || m_nmtProcess->state() != QProcess::Running || !m_polishAvailable) {
        emit translationPolishedReady(reqId, rawVi);
        return;
    }
    QJsonObject req;
    req["action"] = "polish_batch";
    QJsonArray items;
    QJsonObject item;
    item["id"] = reqId;
    item["text"] = sourceEn;
    item["raw"] = rawVi;
    items.append(item);
    req["items"] = items;
    m_nmtProcess->write(QJsonDocument(req).toJson(QJsonDocument::Compact) + "\n");
}

void OfflineTranslator::onNmtOutputReady() {
    if (!m_nmtProcess) return;
    
    while (m_nmtProcess->canReadLine()) {
        QByteArray out = m_nmtProcess->readLine().trimmed();
        if (out.startsWith("{") && out.endsWith("}")) {
            QJsonDocument doc = QJsonDocument::fromJson(out);
            if (doc.isObject()) {
                if (doc.object().contains("available")) {
                    // Initial ready message from daemon
                    m_nmtInitialized = true;
                    m_nmtReady = doc.object().value("available").toBool();
                    m_nmtStatus = m_nmtReady ? ModelStatus::Ready : ModelStatus::Crashed;
                    m_polishAvailable = doc.object().value("polish_available").toBool();
                    m_polishModelName = doc.object().value("polish_model").toString();
                    QString pStatus = doc.object().value("polish_status").toString();
                    if (m_polishAvailable) {
                        m_polishStatus = ModelStatus::Ready;
                    } else if (pStatus == "loading" || m_polishModelName == "loading") {
                        m_polishStatus = ModelStatus::Loading;
                    } else if (pStatus == "crashed") {
                        m_polishStatus = ModelStatus::Crashed;
                    } else {
                        m_polishStatus = ModelStatus::Loading;
                    }
                    if (m_nmtReady) {
                        qDebug() << "Local NMT daemon ready:"
                                 << doc.object().value("model").toString()
                                 << doc.object().value("device").toString()
                                 << "Polish available:" << m_polishAvailable
                                 << "Polish model:" << m_polishModelName;
                    } else {
                        qWarning() << "Local NMT model is unavailable; network access remains disabled.";
                    }
                    emit nmtReady();
                    emit modelStatusChanged();
                } else if (doc.object().contains("polish_available") && !doc.object().contains("available")) {
                    // Async polish-ready / status notification from background loader thread
                    m_polishAvailable = doc.object().value("polish_available").toBool();
                    QString pStatus = doc.object().value("polish_status").toString();
                    if (doc.object().contains("polish_model"))
                        m_polishModelName = doc.object().value("polish_model").toString();
                    if (m_polishAvailable) {
                        m_polishStatus = ModelStatus::Ready;
                        qDebug() << "Polish model now available:" << m_polishModelName;
                        emit polishModelReady();
                    } else if (pStatus == "crashed" || doc.object().contains("polish_error")) {
                        m_polishStatus = ModelStatus::Crashed;
                        m_polishError = doc.object().value("polish_error").toString();
                        qWarning() << "Polish model crashed/failed:" << m_polishError;
                    } else if (pStatus == "loading") {
                        m_polishStatus = ModelStatus::Loading;
                    }
                    emit modelStatusChanged();
                } else if (doc.object().contains("action") && doc.object().value("action").toString() == "status_response") {
                    m_nmtReady = doc.object().value("nmt_ready").toBool();
                    m_nmtStatus = m_nmtReady ? ModelStatus::Ready : ModelStatus::Crashed;
                    m_polishAvailable = doc.object().value("polish_ready").toBool();
                    QString pStatus = doc.object().value("polish_status").toString();
                    if (m_polishAvailable) {
                        m_polishStatus = ModelStatus::Ready;
                    } else if (pStatus == "crashed") {
                        m_polishStatus = ModelStatus::Crashed;
                    } else if (pStatus == "loading") {
                        m_polishStatus = ModelStatus::Loading;
                    }
                    emit modelStatusChanged();
                } else if (doc.object().contains("results")) {
                    QJsonArray results = doc.object().value("results").toArray();
                    for (const QJsonValue &val : results) {
                        QJsonObject obj = val.toObject();
                        int reqId = obj.value("id").toInt();
                        QString translated = obj.value("translated").toString();
                        bool isPolished = (obj.value("stage").toString() == "polish");
                        if (isPolished) {
                            emit translationPolishedReady(reqId, postProcessTranslation(translated));
                        } else {
                            emit translationResultReady(reqId, postProcessTranslation(translated));
                        }
                    }
                } else if (doc.object().contains("failures")) {
                    QJsonArray failures = doc.object().value("failures").toArray();
                    for (const QJsonValue &val : failures) {
                        QJsonObject obj = val.toObject();
                        emit translationFailed(
                            obj.value("id").toInt(), obj.value("error").toString());
                    }
                } else if (doc.object().contains("error")) {
                    m_nmtError = doc.object().value("error").toString();
                    emit nmtProcessFailed(m_nmtError);
                    emit modelStatusChanged();
                } else if (doc.object().contains("translated")) {
                    int reqId = doc.object().value("id").toInt();
                    QString translated = doc.object().value("translated").toString();
                    bool isPolished = (doc.object().value("stage").toString() == "polish");
                    if (isPolished) {
                        emit translationPolishedReady(reqId, postProcessTranslation(translated));
                    } else {
                        emit translationResultReady(reqId, postProcessTranslation(translated));
                    }
                }
            }
        }
    }
}

void OfflineTranslator::queryNmtModelAsync(int reqId, const QString &text) {

    if (!m_nmtReady || !m_nmtProcess || m_nmtProcess->state() != QProcess::Running) {
        emit translationResultReady(reqId, text);
        return;
    }

    m_translationQueue.append(qMakePair(reqId, text));
    if (m_translationQueue.size() >= kPreferredBatchSize) {
        flushTranslationQueue();
    } else {
        if (!m_batchTimer.isActive()) {
            m_batchTimer.start(5);
        }
    }
}

void OfflineTranslator::cancelQueuedTranslations() {
    m_batchTimer.stop();
    m_translationQueue.clear();
}

void OfflineTranslator::clearCache() {
    cancelQueuedTranslations();
    if (m_nmtProcess && m_nmtProcess->state() == QProcess::Running) {
        QJsonObject req;
        req["action"] = "clear_cache";
        QByteArray payload = QJsonDocument(req).toJson(QJsonDocument::Compact) + "\n";
        m_nmtProcess->write(payload);
    }
    const QStringList paths = {
        QDir::home().filePath(".local/share/readDoc/translation_memory.sqlite3"),
        QDir::home().filePath(".local/share/readDoc/translation_memory.sqlite3-wal"),
        QDir::home().filePath(".local/share/readDoc/translation_memory.sqlite3-shm"),
        QDir::home().filePath("AppData/Roaming/readDoc/translation_memory.sqlite3"),
        QDir::home().filePath("AppData/Roaming/readDoc/translation_memory.sqlite3-wal"),
        QDir::home().filePath("AppData/Roaming/readDoc/translation_memory.sqlite3-shm")
    };
    for (const QString &p : paths) {
        if (QFile::exists(p)) {
            QFile::remove(p);
        }
    }
}

void OfflineTranslator::flushTranslationQueue() {
    if (m_translationQueue.isEmpty()) return;
    if (!m_nmtReady || !m_nmtProcess || m_nmtProcess->state() != QProcess::Running) {
        for (const auto &item : m_translationQueue) {
            emit translationFailed(item.first, "Model local không chạy");
        }
        m_translationQueue.clear();
        return;
    }

    QJsonObject req;
    QJsonArray batchArr;
    for (const auto &item : m_translationQueue) {
        QJsonObject batchItem;
        batchItem["id"] = item.first;
        batchItem["text"] = item.second;
        batchArr.append(batchItem);
    }
    req["batch"] = batchArr;
    
    QByteArray payload = QJsonDocument(req).toJson(QJsonDocument::Compact) + "\n";
    m_nmtProcess->write(payload);
    
    m_translationQueue.clear();
}

QString OfflineTranslator::postProcessTranslation(const QString &raw) {
    if (raw.isEmpty()) return "";
    QString text = raw;

    text.replace(QRegularExpression("\\s+"), " ");
    text.replace(QRegularExpression("\\s+([.,!?:;])"), "\\1");
    text.replace(" / ", " ");
    text.replace(" /", "");
    text.replace("/ ", "");

    text = text.trimmed();
    if (!text.isEmpty() && text[0].isLower()) {
        text[0] = text[0].toUpper();
    }

    return text;
}

void OfflineTranslator::requestAsyncTranslation(int reqId, const QString &sentence) {
    QString trimmed = sentence.trimmed();
    if (trimmed.isEmpty()) {
        emit translationResultReady(reqId, "");
        return;
    }

    if (m_nmtReady) {
        queryNmtModelAsync(reqId, trimmed);
        return;
    }

    emit translationResultReady(reqId, trimmed);
}
