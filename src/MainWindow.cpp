#include "readDoc/MainWindow.h"
#include "readDoc/Data/PdfExtractor.h"
#include <QFileDialog>
#include <QInputDialog>
#include <QFileInfo>
#include <QMimeData>
#include <QHBoxLayout>
#include <QVBoxLayout>
#include <QMessageBox>

MainWindow::MainWindow(QWidget *parent)
    : QMainWindow(parent)
{
    m_translator = new OfflineTranslator(this);
    setAcceptDrops(true);
    resize(1200, 800);
    setWindowTitle("readDoc — Secure Offline Document Reader & Translator");

    setupUi();
}

MainWindow::~MainWindow() = default;

void MainWindow::openDocument(const QString &filePath, bool bilingual, int initialPage) {
    openFile(filePath);
    if (bilingual) {
        switchToSplitView();
        m_splitReader->goToPage(initialPage);
    }
}

void MainWindow::setupUi() {
    QWidget *central = new QWidget(this);
    setCentralWidget(central);
    central->setStyleSheet("background-color: #121212; color: #ffffff;");

    QHBoxLayout *root = new QHBoxLayout(central);
    root->setContentsMargins(0, 0, 0, 0);
    root->setSpacing(0);

    // --- Sidebar ---
    m_sidebar = new QWidget(this);
    m_sidebar->setFixedWidth(240);
    m_sidebar->setStyleSheet("background-color: #181818; border-right: 1px solid #282828;");

    QVBoxLayout *sideLy = new QVBoxLayout(m_sidebar);
    sideLy->setContentsMargins(14, 16, 14, 16);
    sideLy->setSpacing(12);

    QLabel *logo = new QLabel("📖 readDoc", m_sidebar);
    logo->setStyleSheet("font-size: 18px; font-weight: 800; color: #ffffff; margin-bottom: 8px;");
    sideLy->addWidget(logo);

    m_openBtn = new QPushButton("📂 Mở Tài Liệu...", m_sidebar);
    m_openBtn->setCursor(Qt::PointingHandCursor);
    m_openBtn->setStyleSheet(
        "QPushButton { background-color: #2d5af6; color: #ffffff; border: none; border-radius: 8px; padding: 10px; font-size: 13px; font-weight: 600; }"
        "QPushButton:hover { background-color: #406cf8; }"
    );
    connect(m_openBtn, &QPushButton::clicked, this, &MainWindow::openFileDialog);
    sideLy->addWidget(m_openBtn);

    QLabel *recentHeader = new QLabel("TÀI LIỆU GẦN ĐÂY", m_sidebar);
    recentHeader->setStyleSheet("color: #777; font-size: 11px; font-weight: 700; margin-top: 12px;");
    sideLy->addWidget(recentHeader);

    m_recentList = new QListWidget(m_sidebar);
    m_recentList->setStyleSheet(
        "QListWidget { background: transparent; border: none; color: #bbb; font-size: 13px; }"
        "QListWidget::item { padding: 8px; border-radius: 6px; }"
        "QListWidget::item:hover { background: #242424; color: #fff; }"
        "QListWidget::item:selected { background: #2d5af6; color: #fff; }"
    );
    connect(m_recentList, &QListWidget::itemClicked, this, [this](QListWidgetItem *item) {
        openFile(item->data(Qt::UserRole).toString());
    });
    sideLy->addWidget(m_recentList, 1);

    QPushButton *clearCacheSidebarBtn = new QPushButton("🗑 Xóa Bộ Nhớ Cache", m_sidebar);
    clearCacheSidebarBtn->setCursor(Qt::PointingHandCursor);
    clearCacheSidebarBtn->setStyleSheet(
        "QPushButton { background-color: #24282f; color: #90a4ae; border: 1px solid #37474f; border-radius: 6px; padding: 7px; font-size: 11px; font-weight: 600; }"
        "QPushButton:hover { background-color: #37474f; color: #ffffff; }"
    );
    connect(clearCacheSidebarBtn, &QPushButton::clicked, this, [this]() {
        if (QMessageBox::question(this, "Xác nhận xóa Cache",
            "Bạn có chắc chắn muốn xóa toàn bộ bộ nhớ đệm bản dịch không?\n"
            "Các tài liệu sau này sẽ được dịch lại từ đầu bằng GPU.",
            QMessageBox::Yes | QMessageBox::No) == QMessageBox::Yes) {
            if (m_translator) m_translator->clearCache();
            QMessageBox::information(this, "Hoàn tất", "Đã xóa toàn bộ bộ nhớ đệm bản dịch thành công!");
        }
    });
    sideLy->addWidget(clearCacheSidebarBtn);

    root->addWidget(m_sidebar);

    // --- Main Right Container ---
    QWidget *mainContainer = new QWidget(this);
    QVBoxLayout *mainLy = new QVBoxLayout(mainContainer);
    mainLy->setContentsMargins(0, 0, 0, 0);
    mainLy->setSpacing(0);

    // Top Bar
    m_topBar = new QWidget(mainContainer);
    m_topBar->setFixedHeight(44);
    m_topBar->setStyleSheet("background-color: #1a1a1a; border-bottom: 1px solid #282828;");

    QHBoxLayout *topLy = new QHBoxLayout(m_topBar);
    topLy->setContentsMargins(16, 0, 16, 0);

    m_statusLabel = new QLabel("🔒 Chế độ Bảo mật 100% Offline — Sẵn sàng đọc tài liệu", m_topBar);
    m_statusLabel->setStyleSheet("color: #00e676; font-size: 12px; font-weight: 500;");

    m_singleViewBtn = new QPushButton("📄 Đọc Đơn", m_topBar);
    m_splitViewBtn  = new QPushButton("🌐 Đọc Song Ngữ", m_topBar);

    QString modeBtnStyle =
        "QPushButton { background: #282828; color: #ccc; border: 1px solid #383838; border-radius: 5px; padding: 5px 12px; font-size: 12px; font-weight: 500; }"
        "QPushButton:hover { background: #333; color: #fff; }";

    m_singleViewBtn->setStyleSheet(modeBtnStyle);
    m_splitViewBtn->setStyleSheet(modeBtnStyle);

    connect(m_singleViewBtn, &QPushButton::clicked, this, &MainWindow::switchToSingleView);
    connect(m_splitViewBtn,  &QPushButton::clicked, this, &MainWindow::switchToSplitView);

    topLy->addWidget(m_statusLabel, 1);
    topLy->addWidget(m_singleViewBtn);
    topLy->addWidget(m_splitViewBtn);

    mainLy->addWidget(m_topBar);

    // Stacked Widgets
    m_centralStack = new QStackedWidget(mainContainer);

    m_readerWidget = new ReaderWidget(m_centralStack);
    m_splitReader  = new SplitViewReader(m_translator, m_centralStack);

    m_centralStack->addWidget(m_readerWidget);
    m_centralStack->addWidget(m_splitReader);

    mainLy->addWidget(m_centralStack, 1);

    root->addWidget(mainContainer, 1);
}

void MainWindow::openFileDialog() {
    QString filePath = QFileDialog::getOpenFileName(
        this,
        "Chọn Tài Liệu Để Đọc",
        "",
        "Tất cả Tài Liệu (*.pdf *.docx *.txt *.log *.md *.markdown *.png *.jpg *.jpeg *.webp *.bmp);;PDF Documents (*.pdf);;Word Documents (*.docx);;Text & Markdown (*.txt *.log *.md *.markdown);;Images (*.png *.jpg *.jpeg *.webp *.bmp)"
    );

    if (!filePath.isEmpty()) {
        openFile(filePath);
    }
}

void MainWindow::openFile(const QString &filePath) {
    if (filePath.isEmpty() || !QFileInfo::exists(filePath)) {
        return;
    }

    QString password;
    if (DocumentParser::detectType(filePath) == DocumentType::PDF) {
        if (PdfExtractor::isPasswordRequired(filePath)) {
            bool ok = false;
            while (true) {
                password = QInputDialog::getText(
                    this,
                    "Tài Liệu Được Bảo Vệ",
                    QString("Tài liệu '%1' được bảo vệ bằng mật khẩu.\nVui lòng nhập mật khẩu để mở:").arg(QFileInfo(filePath).fileName()),
                    QLineEdit::Password,
                    "",
                    &ok
                );
                if (!ok) {
                    return;
                }
                if (PdfExtractor::verifyPassword(filePath, password)) {
                    break;
                } else {
                    QMessageBox::warning(
                        this,
                        "Sai Mật Khẩu",
                        "Mật khẩu bạn vừa nhập không chính xác. Vui lòng thử lại!"
                    );
                }
            }
        }
    }

    m_currentDoc = DocumentParser::parseDocument(filePath, password);
    m_statusLabel->setText("🔒 Đang mở tài liệu bảo mật: " + m_currentDoc.fileName);

    m_readerWidget->loadDocument(m_currentDoc);
    m_splitLoadedPath.clear();

    m_centralStack->setCurrentWidget(m_readerWidget);

    // Add to recent sidebar list if not exists
    bool exists = false;
    for (int i = 0; i < m_recentList->count(); ++i) {
        if (m_recentList->item(i)->data(Qt::UserRole).toString() == filePath) {
            exists = true;
            break;
        }
    }
    if (!exists) {
        QListWidgetItem *item = new QListWidgetItem(m_currentDoc.fileName, m_recentList);
        item->setData(Qt::UserRole, filePath);
    }
}

void MainWindow::switchToSingleView() {
    m_centralStack->setCurrentWidget(m_readerWidget);
}

void MainWindow::switchToSplitView() {
    if (!m_currentDoc.filePath.isEmpty() && m_splitLoadedPath != m_currentDoc.filePath) {
        m_splitReader->loadDocument(m_currentDoc);
        m_splitLoadedPath = m_currentDoc.filePath;
    }
    m_centralStack->setCurrentWidget(m_splitReader);
}

void MainWindow::dragEnterEvent(QDragEnterEvent *event) {
    if (event->mimeData()->hasUrls()) {
        event->acceptProposedAction();
    }
}

void MainWindow::dropEvent(QDropEvent *event) {
    const QList<QUrl> urls = event->mimeData()->urls();
    if (!urls.isEmpty()) {
        QString filePath = urls.first().toLocalFile();
        if (!filePath.isEmpty()) {
            openFile(filePath);
        }
    }
}
