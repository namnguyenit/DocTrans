#pragma once

#include <QWidget>
#include <QTextBrowser>
#include <QLabel>
#include <QPushButton>
#include <QVBoxLayout>
#include <QHBoxLayout>
#include <QStackedWidget>
#include <QPdfDocument>
#include <QPdfView>

#include "readDoc/Data/DocumentParser.h"

enum class ReaderTheme {
    Dark,
    Sepia,
    Light
};

class ReaderWidget : public QWidget {
public:
    explicit ReaderWidget(QWidget *parent = nullptr);

    void loadDocument(const DocumentContent &doc);

private:
    void zoomIn();
    void zoomOut();
    void setTheme(ReaderTheme theme);
    QStackedWidget     *m_contentStack;
    QPdfDocument       *m_pdfDocument;
    QPdfView           *m_pdfView;
    QTextBrowser       *m_textBrowser;
    ReaderTheme         m_theme = ReaderTheme::Dark;
    int                 m_fontSize = 15;

    // Toolbar controls
    QWidget     *m_toolBar;
    QLabel      *m_titleLabel;
    QPushButton *m_themeDarkBtn;
    QPushButton *m_themeSepiaBtn;
    QPushButton *m_themeLightBtn;
    QPushButton *m_zoomInBtn;
    QPushButton *m_zoomOutBtn;

    void applyThemeCss();
};
