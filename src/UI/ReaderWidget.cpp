#include "readDoc/UI/ReaderWidget.h"
#include <QInputDialog>

ReaderWidget::ReaderWidget(QWidget *parent)
    : QWidget(parent)
{
    QVBoxLayout *root = new QVBoxLayout(this);
    root->setContentsMargins(0, 0, 0, 0);
    root->setSpacing(0);

    // --- Toolbar ---
    m_toolBar = new QWidget(this);
    m_toolBar->setFixedHeight(40);
    m_toolBar->setStyleSheet("background-color: #1e1e1e; border-bottom: 1px solid #2d2d2d;");

    QHBoxLayout *barLy = new QHBoxLayout(m_toolBar);
    barLy->setContentsMargins(12, 0, 12, 0);
    barLy->setSpacing(8);

    m_titleLabel = new QLabel("Chưa mở tài liệu", m_toolBar);
    m_titleLabel->setStyleSheet("color: #e0e0e0; font-size: 13px; font-weight: 600;");
    barLy->addWidget(m_titleLabel, 1);

    // Themes
    m_themeDarkBtn = new QPushButton("🌙 Dark", m_toolBar);
    m_themeSepiaBtn = new QPushButton("📜 Sepia", m_toolBar);
    m_themeLightBtn = new QPushButton("☀️ Light", m_toolBar);

    QString btnStyle = 
        "QPushButton { color: #aaa; background: #2b2b2b; border: 1px solid #3d3d3d; border-radius: 4px; padding: 4px 10px; font-size: 11px; }"
        "QPushButton:hover { color: #fff; background: #3b3b3b; }";

    m_themeDarkBtn->setStyleSheet(btnStyle);
    m_themeSepiaBtn->setStyleSheet(btnStyle);
    m_themeLightBtn->setStyleSheet(btnStyle);

    barLy->addWidget(m_themeDarkBtn);
    barLy->addWidget(m_themeSepiaBtn);
    barLy->addWidget(m_themeLightBtn);

    // Zoom
    m_zoomOutBtn = new QPushButton("−", m_toolBar);
    m_zoomInBtn = new QPushButton("+", m_toolBar);
    m_zoomOutBtn->setStyleSheet(btnStyle);
    m_zoomInBtn->setStyleSheet(btnStyle);

    barLy->addWidget(m_zoomOutBtn);
    barLy->addWidget(m_zoomInBtn);

    root->addWidget(m_toolBar);

    // --- Content Area: reflowed text or the original local PDF ---
    m_contentStack = new QStackedWidget(this);

    m_textBrowser = new QTextBrowser(m_contentStack);
    m_textBrowser->setOpenExternalLinks(false);
    m_textBrowser->setStyleSheet("QTextBrowser { background-color: #121212; color: #e0e0e0; border: none; padding: 24px; font-size: 15px; line-height: 1.6; }");

    m_pdfDocument = new QPdfDocument(this);
    m_pdfView = new QPdfView(m_contentStack);
    m_pdfView->setDocument(m_pdfDocument);
    m_pdfView->setPageMode(QPdfView::PageMode::MultiPage);
    m_pdfView->setZoomMode(QPdfView::ZoomMode::FitToWidth);
    m_pdfView->setDocumentMargins(QMargins(18, 18, 18, 18));
    m_pdfView->setPageSpacing(12);
    m_pdfView->setStyleSheet("background-color:#2b2d30;border:none;");

    m_contentStack->addWidget(m_textBrowser);
    m_contentStack->addWidget(m_pdfView);

    root->addWidget(m_contentStack, 1);

    // Connections
    connect(m_themeDarkBtn,  &QPushButton::clicked, this, [this]() { setTheme(ReaderTheme::Dark); });
    connect(m_themeSepiaBtn, &QPushButton::clicked, this, [this]() { setTheme(ReaderTheme::Sepia); });
    connect(m_themeLightBtn, &QPushButton::clicked, this, [this]() { setTheme(ReaderTheme::Light); });
    connect(m_zoomInBtn,     &QPushButton::clicked, this, &ReaderWidget::zoomIn);
    connect(m_zoomOutBtn,    &QPushButton::clicked, this, &ReaderWidget::zoomOut);

    connect(m_pdfDocument, &QPdfDocument::passwordRequired, this, [this]() {
        bool ok = false;
        QString password = QInputDialog::getText(
            this,
            "Tài Liệu Được Bảo Vệ",
            "Tài liệu PDF được bảo vệ bằng mật khẩu.\nVui lòng nhập mật khẩu:",
            QLineEdit::Password,
            "",
            &ok
        );
        if (ok && !password.isEmpty()) {
            m_pdfDocument->setPassword(password);
        }
    });
}

void ReaderWidget::loadDocument(const DocumentContent &doc) {
    m_titleLabel->setText(doc.fileName);
    const bool supportsReflowTheme = doc.type != DocumentType::PDF;
    m_themeDarkBtn->setVisible(supportsReflowTheme);
    m_themeSepiaBtn->setVisible(supportsReflowTheme);
    m_themeLightBtn->setVisible(supportsReflowTheme);

    if (doc.type == DocumentType::PDF) {
        // PDFs must open as the real document. Extracted text loses page geometry,
        // images, columns and table borders and is only suitable for translation.
        m_pdfDocument->close();
        if (!doc.password.isEmpty()) {
            m_pdfDocument->setPassword(doc.password);
        }
        m_pdfDocument->load(doc.filePath);
        m_pdfView->setZoomMode(QPdfView::ZoomMode::FitToWidth);
        m_contentStack->setCurrentWidget(m_pdfView);
    } else {
        if (!doc.htmlContent.isEmpty()) {
            m_textBrowser->setHtml(doc.htmlContent);
        } else {
            m_textBrowser->setPlainText(doc.plainText);
        }
        m_contentStack->setCurrentWidget(m_textBrowser);
        applyThemeCss();
    }
}

void ReaderWidget::setTheme(ReaderTheme theme) {
    m_theme = theme;
    applyThemeCss();
}

void ReaderWidget::zoomIn() {
    if (m_contentStack->currentWidget() == m_pdfView) {
#if QT_VERSION < QT_VERSION_CHECK(6, 4, 0)
        m_pdfView->setZoomMode(QPdfView::ZoomMode::CustomZoom);
#else
        m_pdfView->setZoomMode(QPdfView::ZoomMode::Custom);
#endif
        m_pdfView->setZoomFactor(qMin(3.0, m_pdfView->zoomFactor() + 0.15));
        return;
    }
    m_fontSize = qMin(32, m_fontSize + 2);
    applyThemeCss();
}

void ReaderWidget::zoomOut() {
    if (m_contentStack->currentWidget() == m_pdfView) {
#if QT_VERSION < QT_VERSION_CHECK(6, 4, 0)
        m_pdfView->setZoomMode(QPdfView::ZoomMode::CustomZoom);
#else
        m_pdfView->setZoomMode(QPdfView::ZoomMode::Custom);
#endif
        m_pdfView->setZoomFactor(qMax(0.5, m_pdfView->zoomFactor() - 0.15));
        return;
    }
    m_fontSize = qMax(10, m_fontSize - 2);
    applyThemeCss();
}

void ReaderWidget::applyThemeCss() {
    QString bg, fg;
    switch (m_theme) {
        case ReaderTheme::Dark:
            bg = "#121212";
            fg = "#e0e0e0";
            break;
        case ReaderTheme::Sepia:
            bg = "#fbf0d9";
            fg = "#5f4b32";
            break;
        case ReaderTheme::Light:
            bg = "#ffffff";
            fg = "#222222";
            break;
    }

    QString css = QString(
        "QTextBrowser { background-color: %1; color: %2; border: none; padding: 28px; font-size: %3px; line-height: 1.6; }"
    ).arg(bg, fg).arg(m_fontSize);

    m_textBrowser->setStyleSheet(css);
}
