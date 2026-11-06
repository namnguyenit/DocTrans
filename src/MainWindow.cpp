#include "readDoc/MainWindow.h"
#include "readDoc/Data/PdfExtractor.h"
#include <QFileDialog>
#include <QInputDialog>
#include <QFileInfo>
#include <QMimeData>
#include <QHBoxLayout>
#include <QVBoxLayout>
#include <QMessageBox>
#include <QFutureWatcher>
#include <QtConcurrentRun>
#include <QDir>
#include <QFile>
#include <QProgressDialog>

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
    addDocument(filePath, bilingual, initialPage);
}

void MainWindow::openDocuments(const QStringList &paths, bool bilingual) {
    for (const QString &path : paths) addDocument(path, bilingual);
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
    auto *batchButton = new QPushButton("📚 Dịch nhiều tài liệu...", m_sidebar);
    batchButton->setStyleSheet(m_openBtn->styleSheet());
    connect(batchButton, &QPushButton::clicked, this, &MainWindow::openBatchDialog);
    sideLy->addWidget(batchButton);
    m_exportAllBtn = new QPushButton("Xuất tất cả bản dịch...", m_sidebar);
    m_exportAllBtn->setEnabled(false);
    connect(m_exportAllBtn, &QPushButton::clicked, this, &MainWindow::exportAllDocuments);
    sideLy->addWidget(m_exportAllBtn);
    m_progressTimer = new QTimer(this);
    m_progressTimer->setSingleShot(true);
    connect(m_progressTimer, &QTimer::timeout, this, &MainWindow::updateBatchStatus);

    QLabel *recentHeader = new QLabel("TÀI LIỆU ĐANG MỞ", m_sidebar);
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
        for (auto it = m_sessions.cbegin(); it != m_sessions.cend(); ++it) {
            if (it.value()->item == item) {
                m_documentTabs->setCurrentWidget(it.key());
                return;
            }
        }
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

    m_documentTabs = new QTabWidget(mainContainer);
    m_documentTabs->setTabsClosable(true);
    m_documentTabs->setMovable(true);
    m_documentTabs->setDocumentMode(true);
    m_documentTabs->setStyleSheet(
        "QTabBar::tab { background:#24282f; color:#b8c4d4; padding:9px 14px; }"
        "QTabBar::tab:selected { background:#2d5af6; color:white; }");
    connect(m_documentTabs, &QTabWidget::currentChanged, this, &MainWindow::activateDocument);
    connect(m_documentTabs, &QTabWidget::tabCloseRequested, this, &MainWindow::closeDocument);
    mainLy->addWidget(m_documentTabs, 1);

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
    addDocument(filePath, false);
}

void MainWindow::openBatchDialog() {
    const auto paths = QFileDialog::getOpenFileNames(this, "Chọn các tài liệu cần dịch", {},
        "Tài liệu (*.pdf *.docx *.txt *.log *.md *.markdown)");
    openDocuments(paths, true);
}

void MainWindow::addDocument(const QString &path, bool bilingual, int initialPage) {
    const QFileInfo info(path);
    if (!info.exists() || !info.isFile()) return;
    const QString absolute = info.canonicalFilePath();
    for (const auto &session : m_sessions) {
        if (session->path == absolute) {
            if (session->failed && !session->ready) {
                session->failed = false;
                m_parseQueue.enqueue(session);
                startParsing();
            }
            session->bilingual = session->bilingual || bilingual;
            if (bilingual && session->ready) startTranslation(session);
            m_documentTabs->setCurrentWidget(session->page);
            activateDocument(m_documentTabs->currentIndex());
            return;
        }
    }
    auto session = QSharedPointer<DocumentSession>::create();
    session->path = absolute;
    session->bilingual = bilingual;
    session->initialPage = initialPage;
    session->status = "Chờ đọc tài liệu...";
    session->stack = new QStackedWidget(m_documentTabs);
    session->page = session->stack;
    session->placeholder = new QLabel("Đang chuẩn bị tài liệu...", session->stack);
    session->placeholder->setAlignment(Qt::AlignCenter);
    session->placeholder->setWordWrap(true);
    session->stack->addWidget(session->placeholder);
    session->item = new QListWidgetItem(info.fileName() + "\n" + session->status, m_recentList);
    session->item->setToolTip(absolute);
    m_sessions.insert(session->page, session);
    const int index = m_documentTabs->addTab(session->page, info.fileName());
    m_documentTabs->setTabToolTip(index, absolute);
    m_documentTabs->setCurrentIndex(index);
    m_parseQueue.enqueue(session);
    startParsing();
    updateBatchStatus();
}

void MainWindow::startParsing() {
    // Two bounded CPU readers prepare subsequent documents while the GPU works.
    while (m_activeParsers < 2 && !m_parseQueue.isEmpty()) {
        auto session = m_parseQueue.dequeue();
        if (session->closed) continue;
        ++m_activeParsers;
        session->status = "Đang đọc nội dung...";
        session->item->setText(QFileInfo(session->path).fileName() + "\n" + session->status);
        auto *watcher = new QFutureWatcher<ParseResult>(this);
        connect(watcher, &QFutureWatcher<ParseResult>::finished, this, [this, watcher, session]() {
            const ParseResult result = watcher->result();
            watcher->deleteLater();
            --m_activeParsers;
            if (session->closed) { startParsing(); return; }
            if (result.passwordRequired) {
                bool accepted = false;
                const QString password = QInputDialog::getText(this, "Mật khẩu tài liệu",
                    QString("%1\n%2").arg(QFileInfo(session->path).fileName(),
                        session->password.isEmpty() ? "Nhập mật khẩu để tiếp tục:" : "Mật khẩu chưa đúng. Nhập lại:"),
                    QLineEdit::Password, {}, &accepted);
                if (accepted) {
                    session->password = password;
                    m_parseQueue.enqueue(session);
                } else {
                    session->failed = true;
                    session->status = "Đã bỏ qua: cần mật khẩu";
                    session->placeholder->setText(session->status);
                    session->item->setText(QFileInfo(session->path).fileName() + "\n" + session->status);
                }
                startParsing();
                updateBatchStatus();
                return;
            }
            if (!result.error.isEmpty()) {
                session->failed = true;
                session->status = "Không thể đọc: " + result.error;
                session->placeholder->setText(session->status);
                session->item->setText(QFileInfo(session->path).fileName() + "\n" + session->status);
                startParsing();
                updateBatchStatus();
                return;
            }
            session->doc = result.doc;
            session->ready = true;
            session->reader = new ReaderWidget(session->stack);
            session->split = new SplitViewReader(m_translator, session->stack);
            session->split->setForeground(false);
            session->stack->addWidget(session->reader);
            session->stack->addWidget(session->split);
            connect(session->split, &SplitViewReader::progressChanged, this,
                [this, session](int raw, int polished, int total, bool paused, int failed) {
                    if (session->closed) return;
                    session->paused = paused;
                    session->failed = failed > 0;
                    session->complete = session->split->isTranslationComplete();
                    if (paused) session->status = "Đã dừng • có thể tiếp tục";
                    else if (failed > 0) session->status = QString("Có %1 phần bị lỗi").arg(failed);
                    else if (session->complete) session->status = "✓ Hoàn tất";
                    else if (raw < total) session->status = QString("Dịch %1/%2 • Trau chuốt %3/%2").arg(raw).arg(total).arg(polished);
                    else session->status = QString("Trau chuốt %1/%2").arg(polished).arg(total);
                    if (!m_progressTimer->isActive()) m_progressTimer->start(100);
                });
            session->status = "Sẵn sàng đọc";
            if (session->bilingual) startTranslation(session);
            session->item->setText(QFileInfo(session->path).fileName() + "\n" + session->status);
            if (m_documentTabs->currentWidget() == session->page) activateDocument(m_documentTabs->currentIndex());
            startParsing();
            updateBatchStatus();
        });
        const QString path = session->path, password = session->password;
        watcher->setFuture(QtConcurrent::run([path, password]() {
            ParseResult result;
            try {
                if (DocumentParser::detectType(path) == DocumentType::PDF &&
                    PdfExtractor::isPasswordRequired(path) &&
                    (password.isEmpty() || !PdfExtractor::verifyPassword(path, password))) {
                    result.passwordRequired = true;
                    return result;
                }
                QFile file(path);
                if (!file.open(QIODevice::ReadOnly)) {
                    result.error = file.errorString();
                    return result;
                }
                file.close();
                result.doc = DocumentParser::parseDocument(path, password);
                if (result.doc.type == DocumentType::PDF && result.doc.pageLayouts.isEmpty())
                    result.error = "Không trích xuất được nội dung PDF";
            } catch (const std::exception &error) {
                result.error = QString::fromUtf8(error.what());
            } catch (...) {
                result.error = "Định dạng tài liệu không đọc được";
            }
            return result;
        }));
    }
}

void MainWindow::startTranslation(const QSharedPointer<DocumentSession> &session) {
    if (!session->ready || session->started || session->closed) return;
    if (session->doc.type == DocumentType::IMAGE) {
        session->status = "Ảnh: chỉ hỗ trợ xem, chưa dịch OCR ảnh riêng";
        session->bilingual = false;
        return;
    }
    session->started = true;
    session->split->loadDocument(session->doc);
    session->split->goToPage(session->initialPage);
    if (session->bilingual) session->stack->setCurrentWidget(session->split);
}

void MainWindow::activateDocument(int index) {
    auto session = m_sessions.value(m_documentTabs->widget(index));
    for (const auto &other : m_sessions)
        if (other->split && (other != session || !session->bilingual)) other->split->setForeground(false);
    m_readerWidget = session ? session->reader : nullptr;
    m_splitReader = session ? session->split : nullptr;
    m_singleViewBtn->setEnabled(session && session->ready);
    m_splitViewBtn->setEnabled(session && session->ready);
    if (!session || !session->ready) { updateBatchStatus(); return; }
    m_currentDoc = session->doc;
    m_recentList->setCurrentItem(session->item);
    if (session->bilingual) {
        startTranslation(session);
        if (session->bilingual) {
            session->stack->setCurrentWidget(session->split);
            session->split->setForeground(true);
        }
    }
    if (!session->bilingual) {
        if (!session->singleLoaded) {
            session->reader->loadDocument(session->doc);
            session->singleLoaded = true;
        }
        session->stack->setCurrentWidget(session->reader);
    }
    updateBatchStatus();
}

void MainWindow::closeDocument(int index) {
    QWidget *page = m_documentTabs->widget(index);
    auto session = m_sessions.take(page);
    if (!session) return;
    session->closed = true;
    if (session->split) session->split->stopTranslation();
    delete session->item;
    session->item = nullptr;
    m_documentTabs->removeTab(index);
    page->deleteLater();
    startParsing();
    activateDocument(m_documentTabs->currentIndex());
}

void MainWindow::updateBatchStatus() {
    int translated = 0, running = 0, waiting = 0;
    for (const auto &session : m_sessions) {
        if (session->complete) ++translated;
        else if (session->started && !session->paused && !session->failed) ++running;
        else if (!session->ready && !session->failed) ++waiting;
        const QString name = QFileInfo(session->path).fileName();
        const QString text = name + "\n" + session->status;
        if (session->item->text() != text) session->item->setText(text);
        const int tab = m_documentTabs->indexOf(session->page);
        const QString tabName = (session->complete ? "✓ " : "") + name;
        if (tab >= 0 && m_documentTabs->tabText(tab) != tabName) m_documentTabs->setTabText(tab, tabName);
    }
    m_exportAllBtn->setEnabled(translated > 0);
    if (m_sessions.isEmpty()) m_statusLabel->setText("🔒 Offline • Mở tài liệu hoặc chọn Dịch nhiều tài liệu");
    else m_statusLabel->setText(QString("🔒 Offline • %1 tài liệu • %2 hoàn tất • %3 đang dịch • %4 đang chuẩn bị")
        .arg(m_sessions.size()).arg(translated).arg(running).arg(waiting));
}

void MainWindow::switchToSingleView() {
    auto session = m_sessions.value(m_documentTabs->currentWidget());
    if (!session || !session->ready) return;
    session->bilingual = false;
    activateDocument(m_documentTabs->currentIndex());
}

void MainWindow::switchToSplitView() {
    auto session = m_sessions.value(m_documentTabs->currentWidget());
    if (!session || !session->ready) return;
    session->bilingual = true;
    activateDocument(m_documentTabs->currentIndex());
}

void MainWindow::exportAllDocuments() {
    const QString folder = QFileDialog::getExistingDirectory(this, "Chọn thư mục lưu các bản dịch");
    if (folder.isEmpty()) return;
    QList<QSharedPointer<DocumentSession>> ready;
    for (int i = 0; i < m_documentTabs->count(); ++i) {
        auto session = m_sessions.value(m_documentTabs->widget(i));
        if (session && session->complete && session->split) ready.append(session);
    }
    QProgressDialog progress("Đang xuất các bản dịch...", "Dừng xuất", 0, ready.size(), this);
    progress.setWindowModality(Qt::WindowModal);
    progress.setMinimumDuration(0);
    int exported = 0;
    QStringList errors;
    for (const auto &session : ready) {
        progress.setValue(exported);
        progress.setLabelText(QFileInfo(session->path).fileName());
        QCoreApplication::processEvents();
        if (progress.wasCanceled()) break;
        const QString base = QFileInfo(session->path).completeBaseName() + "_translated";
        QString output = QDir(folder).filePath(base + ".pdf");
        int suffix = 2;
        while (QFileInfo::exists(output)) output = QDir(folder).filePath(base + QString("_%1.pdf").arg(suffix++));
        QString error;
        if (session->split->exportToPdf(output, &error)) ++exported;
        else errors.append(QFileInfo(session->path).fileName() + ": " + error);
    }
    progress.setValue(ready.size());
    QMessageBox::information(this, "Xuất bản dịch", QString("Đã xuất %1 tài liệu vào:\n%2%3")
        .arg(exported).arg(folder, errors.isEmpty() ? "" : "\n\n" + errors.join("\n")));
}

void MainWindow::dragEnterEvent(QDragEnterEvent *event) {
    if (event->mimeData()->hasUrls()) event->acceptProposedAction();
}

void MainWindow::dropEvent(QDropEvent *event) {
    QStringList paths;
    for (const QUrl &url : event->mimeData()->urls()) {
        const QString path = url.toLocalFile();
        if (!path.isEmpty()) paths.append(path);
    }
    openDocuments(paths, paths.size() > 1);
}
