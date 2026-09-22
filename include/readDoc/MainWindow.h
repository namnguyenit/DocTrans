#pragma once

#include <QMainWindow>
#include <QStackedWidget>
#include <QListWidget>
#include <QLabel>
#include <QPushButton>
#include <QDragEnterEvent>
#include <QDropEvent>

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

protected:
    void dragEnterEvent(QDragEnterEvent *event) override;
    void dropEvent(QDropEvent *event) override;

private slots:
    void openFileDialog();
    void openFile(const QString &filePath);
    void switchToSingleView();
    void switchToSplitView();

private:
    OfflineTranslator *m_translator;
    DocumentContent    m_currentDoc;
    QString            m_splitLoadedPath;

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
    QStackedWidget   *m_centralStack;
    ReaderWidget     *m_readerWidget;
    SplitViewReader  *m_splitReader;

    void setupUi();
};
