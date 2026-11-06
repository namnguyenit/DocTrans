#pragma once

#include <QMainWindow>
#include <QStackedWidget>
#include <QListWidget>
#include <QLabel>
#include <QPushButton>
#include <QDragEnterEvent>
#include <QDropEvent>
#include <QTabWidget>
#include <QHash>
#include <QQueue>
#include <QSharedPointer>

#include "readDoc/System/OfflineTranslator.h"
#include "readDoc/Data/DocumentParser.h"
#include "readDoc/UI/ReaderWidget.h"
#include "readDoc/UI/SplitViewReader.h"

class MainWindow : public QMainWindow {
    Q_OBJECT
public:
    explicit MainWindow(QWidget *parent = nullptr);
    ~MainWindow();
    void openDocument(const QString &filePath, bool bilingual = false,
                      int initialPage = 1);
    void openDocuments(const QStringList &paths, bool bilingual = true);

protected:
    void dragEnterEvent(QDragEnterEvent *event) override;
    void dropEvent(QDropEvent *event) override;

private slots:
    void openFileDialog();
    void openFile(const QString &filePath);
    void switchToSingleView();
    void switchToSplitView();
    void openBatchDialog();
    void exportAllDocuments();

private:
    OfflineTranslator *m_translator;
    DocumentContent    m_currentDoc;

    // UI
    QWidget        *m_sidebar;
    QPushButton    *m_openBtn;
    QListWidget    *m_recentList;

    // Top Bar
    QWidget        *m_topBar;
    QLabel         *m_statusLabel;
    QPushButton    *m_singleViewBtn;
    QPushButton    *m_splitViewBtn;

    // Central stack
    ReaderWidget     *m_readerWidget = nullptr;
    SplitViewReader  *m_splitReader = nullptr;
    QTabWidget *m_documentTabs = nullptr;
    QPushButton *m_exportAllBtn = nullptr;
    struct DocumentSession {
        QString path, password, status;
        DocumentContent doc;
        QWidget *page = nullptr;
        QStackedWidget *stack = nullptr;
        ReaderWidget *reader = nullptr;
        SplitViewReader *split = nullptr;
        QLabel *placeholder = nullptr;
        QListWidgetItem *item = nullptr;
        bool ready = false, started = false, bilingual = false, singleLoaded = false;
        bool complete = false, closed = false, failed = false, paused = false;
        int initialPage = 1;
    };
    struct ParseResult {
        DocumentContent doc;
        QString error;
        bool passwordRequired = false;
    };
    QHash<QWidget *, QSharedPointer<DocumentSession>> m_sessions;
    QQueue<QSharedPointer<DocumentSession>> m_parseQueue;
    int m_activeParsers = 0;
    QTimer *m_progressTimer = nullptr;
    void addDocument(const QString &path, bool bilingual, int initialPage = 1);
    void startParsing();
    void activateDocument(int index);
    void closeDocument(int index);
    void startTranslation(const QSharedPointer<DocumentSession> &session);
    void updateBatchStatus();

    void setupUi();
};
