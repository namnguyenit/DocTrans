#include "readDoc/UI/SplitViewReader.h"
#include "readDoc/Data/PdfExtractor.h"

#include <QJsonArray>
#include <QJsonDocument>
#include <QJsonObject>
#include <QHBoxLayout>
#include <QRegularExpression>
#include <QResizeEvent>
#include <QScrollBar>
#include <QSignalBlocker>
#include <QTextDocument>
#include <QUrl>
#include <QVBoxLayout>
#include <QtMath>
#include <QPainter>
#include <QFontMetricsF>
#include <QTextOption>
#include <QMessageBox>
#include <QDesktopServices>
#include <QFileDialog>
#include <QPageSize>
#include <QPdfWriter>
#include <QProgressDialog>

namespace {
QString buttonStyle(const QString &color) {
    return QString(
        "QPushButton { color: #fff; background: %1; border: none; border-radius: 5px; "
        "padding: 5px 10px; font-size: 11px; font-weight: 600; }"
        "QPushButton:hover { opacity: 0.9; }"
        "QPushButton:disabled { color: #777; background: #2a2a2a; }").arg(color);
}

QString navigationStyle() {
    return QStringLiteral(
        "QPushButton { color:#d7e3f4; background:#24282f; border:1px solid #343a43; "
        "border-radius:5px; padding:4px 9px; font-size:12px; }"
        "QPushButton:hover { background:#303640; }"
        "QPushButton:disabled { color:#555; background:#1d1f23; }");
}
}

SplitViewReader::SplitViewReader(OfflineTranslator *translator, QWidget *parent)
    : QWidget(parent), m_translator(translator)
{
    auto *root = new QVBoxLayout(this);
    root->setContentsMargins(0, 0, 0, 0);
    root->setSpacing(0);

    m_headerBar = new QWidget(this);
    m_headerBar->setFixedHeight(42);
    m_headerBar->setStyleSheet(
        "background-color:#1a1a1a; border-bottom:1px solid #2a2a2a;");

    auto *headerLayout = new QHBoxLayout(m_headerBar);
    headerLayout->setContentsMargins(12, 0, 12, 0);
    headerLayout->setSpacing(7);

    m_leftLabel = new QLabel("📄 PDF GỐC", m_headerBar);
    m_leftLabel->setStyleSheet("color:#4a9eff; font-size:12px; font-weight:700;");
    m_rightLabel = new QLabel("🌐 BẢN DỊCH TRỰC QUAN (GPU)", m_headerBar);
    m_rightLabel->setStyleSheet("color:#00e676; font-size:12px; font-weight:700;");

    m_zoomOutBtn = new QPushButton("－", m_headerBar);
    m_zoomOutBtn->setStyleSheet(navigationStyle());
    m_zoomOutBtn->setToolTip("Thu nhỏ (Ctrl + Lăn chuột xuống)");
    
    m_zoomLabel = new QLabel("100%", m_headerBar);
    m_zoomLabel->setStyleSheet("color:#d7e3f4; font-size:11px; font-weight:600; padding:0 4px;");
    
    m_zoomInBtn = new QPushButton("＋", m_headerBar);
    m_zoomInBtn->setStyleSheet(navigationStyle());
    m_zoomInBtn->setToolTip("Phóng to (Ctrl + Lăn chuột lên)");
    
    m_fitWidthBtn = new QPushButton("⛶ Khớp ngang", m_headerBar);
    m_fitWidthBtn->setStyleSheet(navigationStyle());
    m_fitWidthBtn->setToolTip("Tự động co giãn theo chiều ngang");

    connect(m_zoomInBtn, &QPushButton::clicked, this, &SplitViewReader::zoomIn);
    connect(m_zoomOutBtn, &QPushButton::clicked, this, &SplitViewReader::zoomOut);
    connect(m_fitWidthBtn, &QPushButton::clicked, this, &SplitViewReader::fitWidth);

    m_previousBtn = new QPushButton("‹ Trước", m_headerBar);
    m_nextBtn = new QPushButton("Sau ›", m_headerBar);
    m_previousBtn->setStyleSheet(navigationStyle());
    m_nextBtn->setStyleSheet(navigationStyle());
    m_pageSpin = new QSpinBox(m_headerBar);
    m_pageSpin->setRange(1, 1);
    m_pageSpin->setPrefix("Trang ");
    m_pageSpin->setStyleSheet(
        "QSpinBox { color:#d7e3f4;background:#24282f;border:1px solid #343a43;"
        "border-radius:5px;padding:4px 7px;font-size:11px; }");

    m_cancelBtn = new QPushButton("■ Hủy", m_headerBar);
    m_cancelBtn->setStyleSheet(buttonStyle("#8b2f3c"));
    m_cancelBtn->setEnabled(false);

    m_restartBtn = new QPushButton("⚡ Bật lại Model & Tiếp tục", m_headerBar);
    m_restartBtn->setStyleSheet(
        "QPushButton { background:#c62828; color:#ffffff; font-weight:700; font-size:11px; "
        "border:1px solid #ef5350; border-radius:5px; padding:4px 10px; }"
        "QPushButton:hover { background:#d32f2f; }"
    );
    m_restartBtn->setToolTip("Bật lại Model khi bị dừng/crash và tiếp tục dịch hoặc trau chuốt các phần chưa làm");
    m_restartBtn->setVisible(false);
    connect(m_restartBtn, &QPushButton::clicked, this, &SplitViewReader::resumeOrRestartModels);

    m_clearCacheBtn = new QPushButton("🗑 Xóa Cache", m_headerBar);
    m_clearCacheBtn->setStyleSheet(buttonStyle("#37474f"));
    m_clearCacheBtn->setToolTip("Xóa toàn bộ bộ nhớ đệm và dịch lại");
    connect(m_clearCacheBtn, &QPushButton::clicked, this, &SplitViewReader::clearCache);

    m_exportPdfBtn = new QPushButton("📥 Xuất PDF", m_headerBar);
    m_exportPdfBtn->setStyleSheet(buttonStyle("#1565c0"));
    m_exportPdfBtn->setToolTip("Xuất toàn bộ tài liệu đã dịch ra tệp PDF chất lượng cao (300 DPI)");
    connect(m_exportPdfBtn, &QPushButton::clicked, this, &SplitViewReader::exportTranslatedPdf);

    headerLayout->addWidget(m_leftLabel, 1);
    headerLayout->addWidget(m_rightLabel, 1);
    headerLayout->addWidget(m_zoomOutBtn);
    headerLayout->addWidget(m_zoomLabel);
    headerLayout->addWidget(m_zoomInBtn);
    headerLayout->addWidget(m_fitWidthBtn);
    headerLayout->addWidget(m_previousBtn);
    headerLayout->addWidget(m_pageSpin);
    headerLayout->addWidget(m_nextBtn);
    headerLayout->addWidget(m_exportPdfBtn);
    headerLayout->addWidget(m_cancelBtn);
    headerLayout->addWidget(m_restartBtn);
    headerLayout->addWidget(m_clearCacheBtn);
    root->addWidget(m_headerBar);

    m_splitter = new QSplitter(Qt::Horizontal, this);
    m_splitter->setHandleWidth(2);
    m_splitter->setStyleSheet("QSplitter::handle { background-color:#333; }");

    const QString browserStyle = QStringLiteral(
        "QTextBrowser { background-color:#121212; color:#e0e0e0; border:none; "
        "padding:24px; font-size:15px; line-height:1.6; }");
    
    // Left pane (Original Document)
    m_leftStack = new QStackedWidget(m_splitter);
    m_pdfPageScroll = new QScrollArea(m_leftStack);
    m_pdfPageScroll->setWidgetResizable(false);
    m_pdfPageScroll->setAlignment(Qt::AlignHCenter | Qt::AlignTop);
    m_pdfPageScroll->setStyleSheet(
        "QScrollArea { background:#2b2d30; border:none; padding:12px; }");
    m_pdfPageLabel = new QLabel(m_pdfPageScroll);
    m_pdfPageLabel->setAlignment(Qt::AlignCenter);
    m_pdfPageLabel->setStyleSheet(
        "QLabel { background:white; color:#777; border:1px solid #444; }");
    m_pdfPageScroll->setWidget(m_pdfPageLabel);

    m_leftBrowser = new QTextBrowser(m_leftStack);
    m_leftBrowser->setStyleSheet(browserStyle);
    m_leftStack->addWidget(m_pdfPageScroll);
    m_leftStack->addWidget(m_leftBrowser);

    // Right pane (Translated Document - Visual Layout or Text)
    m_rightStack = new QStackedWidget(m_splitter);
    m_rightPdfScroll = new QScrollArea(m_rightStack);
    m_rightPdfScroll->setWidgetResizable(false);
    m_rightPdfScroll->setAlignment(Qt::AlignHCenter | Qt::AlignTop);
    m_rightPdfScroll->setStyleSheet(
        "QScrollArea { background:#2b2d30; border:none; padding:12px; }");
    m_rightPdfLabel = new QLabel(m_rightPdfScroll);
    m_rightPdfLabel->setAlignment(Qt::AlignCenter);
    m_rightPdfLabel->setStyleSheet(
        "QLabel { background:white; color:#777; border:1px solid #444; }");
    m_rightPdfScroll->setWidget(m_rightPdfLabel);

    m_rightBrowser = new QTextBrowser(m_rightStack);
    m_rightBrowser->setStyleSheet(
        "QTextBrowser { background-color:#fdfdfc; color:#24272b; border:none; padding:24px; }");

    m_rightStack->addWidget(m_rightPdfScroll);
    m_rightStack->addWidget(m_rightBrowser);

    m_splitter->addWidget(m_leftStack);
    m_splitter->addWidget(m_rightStack);
    m_splitter->setSizes({600, 600});

    // Install event filters for Ctrl+Wheel Zoom & Middle Click / Left Drag Pan
    m_pdfPageScroll->viewport()->installEventFilter(this);
    m_rightPdfScroll->viewport()->installEventFilter(this);
    m_pdfPageLabel->installEventFilter(this);
    m_rightPdfLabel->installEventFilter(this);

    connect(m_splitter, &QSplitter::splitterMoved, this,
            [this](int, int) {
                updatePdfPageImage();
                updateTranslatedPdfPageImage();
            });
    root->addWidget(m_splitter, 1);

    // Synchronize vertical scrolling
    connect(m_leftBrowser->verticalScrollBar(), &QScrollBar::valueChanged,
            this, &SplitViewReader::syncScrollLeft);
    connect(m_pdfPageScroll->verticalScrollBar(), &QScrollBar::valueChanged,
            this, &SplitViewReader::syncScrollLeft);
    connect(m_rightBrowser->verticalScrollBar(), &QScrollBar::valueChanged,
            this, &SplitViewReader::syncScrollRight);
    connect(m_rightPdfScroll->verticalScrollBar(), &QScrollBar::valueChanged,
            this, &SplitViewReader::syncScrollRight);

    // Synchronize horizontal scrolling
    connect(m_pdfPageScroll->horizontalScrollBar(), &QScrollBar::valueChanged,
            this, [this](int value) {
                if (m_isSyncing) return;
                m_isSyncing = true;
                m_rightPdfScroll->horizontalScrollBar()->setValue(value);
                m_isSyncing = false;
            });
    connect(m_rightPdfScroll->horizontalScrollBar(), &QScrollBar::valueChanged,
            this, [this](int value) {
                if (m_isSyncing) return;
                m_isSyncing = true;
                m_pdfPageScroll->horizontalScrollBar()->setValue(value);
                m_isSyncing = false;
            });

    connect(m_previousBtn, &QPushButton::clicked,
            this, &SplitViewReader::showPreviousPage);
    connect(m_nextBtn, &QPushButton::clicked,
            this, &SplitViewReader::showNextPage);
    connect(m_pageSpin, qOverload<int>(&QSpinBox::valueChanged),
            this, &SplitViewReader::goToPage);
    connect(m_cancelBtn, &QPushButton::clicked,
            this, &SplitViewReader::cancelTranslation);

    if (m_translator) {
        connect(m_translator, &OfflineTranslator::nmtReady,
                this, &SplitViewReader::onNmtReady);
        connect(m_translator, &OfflineTranslator::polishModelReady,
                this, &SplitViewReader::onPolishModelReady);
        connect(m_translator, &OfflineTranslator::translationResultReady,
                this, &SplitViewReader::onTranslationResultReady);
        connect(m_translator, &OfflineTranslator::translationPolishedReady,
                this, &SplitViewReader::onTranslationPolishedReady);
        connect(m_translator, &OfflineTranslator::translationFailed,
                this, &SplitViewReader::onTranslationFailed);
        connect(m_translator, &OfflineTranslator::nmtProcessFailed,
                this, &SplitViewReader::onNmtProcessFailed);
        connect(m_translator, &OfflineTranslator::modelStatusChanged,
                this, &SplitViewReader::onModelStatusChanged);
    }

    m_renderTimer.setSingleShot(true);
    m_renderTimer.setInterval(80);
    connect(&m_renderTimer, &QTimer::timeout,
            this, &SplitViewReader::renderCurrentPage);
}

SplitViewReader::~SplitViewReader() = default;

void SplitViewReader::onNmtReady() {
    if (m_translator && m_translator->isNmtReady() && !m_units.isEmpty()) {
        queueAllPages(m_visiblePage);
        renderCurrentPage();
        updateProgressLabel();
        return;
    }

    if (m_translator && m_translator->isNmtInitialized()) {
        m_rightLabel->setText("🌐 MODEL LOCAL KHÔNG KHẢ DỤNG");
        m_rightLabel->setStyleSheet("color:#ff5252; font-size:12px; font-weight:700;");
        m_rightBrowser->setHtml(
            "<div style='padding:24px;color:#ff5252;'>Không tìm thấy model local. "
            "Ứng dụng không tải model hoặc gửi tài liệu qua mạng.</div>");
    }
}

void SplitViewReader::onPolishModelReady() {
    // Background polish model finished loading — update status label
    if (m_translator && m_translator->isPolishAvailable()) {
        qDebug() << "Polish model online:" << m_translator->polishModelName();
        // Automatically submit any unpolished raw translations to Model 2
        if (!m_cancelled) {
            for (int i = 0; i < m_units.size(); ++i) {
                if (m_results.contains(i) && !m_polishedUnits.contains(i)) {
                    const int reqId = m_nextRequestId++;
                    m_requestToUnit.insert(reqId, i);
                    m_translator->requestPolishOnlyAsync(reqId, m_units.value(i), m_results.value(i));
                }
            }
        }
        updateProgressLabel();
    }
}

void SplitViewReader::onModelStatusChanged() {
    updateProgressLabel();
}

void SplitViewReader::loadDocument(const DocumentContent &doc) {
    m_currentDoc = doc;
    m_renderTimer.stop();
    if (m_translator) m_translator->cancelQueuedTranslations();

    m_requestToUnit.clear();
    m_results.clear();
    m_failedUnits.clear();
    m_polishedUnits.clear();
    m_pendingUnits.clear();
    m_queuedUnits.clear();
    m_inFlight = 0;
    m_received = 0;
    m_cancelled = false;
    m_pageClock.invalidate();

    buildPagesAndUnits(doc);
    {
        const QSignalBlocker blocker(m_pageSpin);
        m_pageSpin->setRange(1, m_pageCount);
        m_pageSpin->setValue(1);
    }
    showPage(1);

    // Queue ENTIRE document for continuous background GPU translation!
    if (m_translator && m_translator->isNmtReady()) {
        queueAllPages(1);
    }
}

void SplitViewReader::goToPage(int page) {
    showPage(page);
}

void SplitViewReader::buildPagesAndUnits(const DocumentContent &doc) {
    if (doc.type == DocumentType::PDF && !doc.pageLayouts.isEmpty()) {
        m_pageTexts.clear();
        m_units.clear();
        m_unitPages.clear();
        m_unitKinds.clear();
        m_pageElements.clear();
        m_pageElements.resize(doc.pageLayouts.size());
        m_blockToUnit.clear();

        for (int pIdx = 0; pIdx < doc.pageLayouts.size(); ++pIdx) {
            const PageLayoutData &layout = doc.pageLayouts[pIdx];
            m_pageTexts.append(layout.text);
            const int pageNum = pIdx + 1;
            QVector<PageElement> &elements = m_pageElements[pIdx];

            for (int bIdx = 0; bIdx < layout.blocks.size(); ++bIdx) {
                const LayoutBlock &blk = layout.blocks[bIdx];
                if (blk.isWatermark || blk.text.trimmed().isEmpty()) {
                    continue;
                }
                const int unitIdx = m_units.size();
                m_units.append(blk.text.trimmed());
                m_unitPages.append(pageNum);
                ElementKind kind = blk.isHeading ? ElementKind::Heading : ElementKind::Paragraph;
                m_unitKinds.append(kind);
                m_blockToUnit.insert({pIdx, bIdx}, unitIdx);

                PageElement element;
                element.kind = kind;
                element.groups.append(QList<int>{unitIdx});
                elements.append(element);
            }
        }
        m_pageCount = qMax(1, m_pageTexts.size());
        return;
    }

    m_pageTexts = doc.pageTexts;
    if (m_pageTexts.isEmpty()) {
        const QStringList blocks = doc.plainText.split(
            QRegularExpression(QStringLiteral("\\n\\s*\\n+")), Qt::SkipEmptyParts);
        QString current;
        for (const QString &block : blocks) {
            if (!current.isEmpty() && current.size() + block.size() > kVirtualPageChars) {
                m_pageTexts.append(current.trimmed());
                current.clear();
            }
            if (!current.isEmpty()) current.append("\n\n");
            current.append(block.trimmed());
        }
        if (!current.trimmed().isEmpty()) m_pageTexts.append(current.trimmed());
    }
    if (m_pageTexts.isEmpty()) m_pageTexts.append(QString());

    m_units.clear();
    m_unitPages.clear();
    m_unitKinds.clear();
    m_pageElements.clear();
    m_pageElements.resize(m_pageTexts.size());
    for (int page = 0; page < m_pageTexts.size(); ++page) {
        buildPageElements(m_pageTexts[page], page + 1);
    }
    m_pageCount = qMax(1, m_pageTexts.size());
}

QVector<int> SplitViewReader::appendTextGroup(const QString &text, int page,
                                              ElementKind kind, bool splitLong) {
    QStringList parts;
    const QString cleaned = text.trimmed();
    if (splitLong && cleaned.size() > kMaxUnitChars) {
        parts = splitOversizedBlock(cleaned);
    } else {
        parts.append(cleaned);
    }
    if (parts.isEmpty()) parts.append(QString());

    QVector<int> indices;
    for (const QString &part : parts) {
        const int index = m_units.size();
        m_units.append(part);
        m_unitPages.append(page);
        m_unitKinds.append(kind);
        indices.append(index);
    }
    return indices;
}

void SplitViewReader::buildPageElements(const QString &pageText, int page) {
    static const QString tablePrefix = QStringLiteral("[[READDOC_TABLE:");
    static const QString imagePrefix = QStringLiteral("[[READDOC_IMAGE:");
    static const QString codePrefix = QStringLiteral("[[READDOC_CODE:");
    static const QString tocPrefix = QStringLiteral("[[READDOC_TOC:");
    static const QString tableSuffix = QStringLiteral("]]");
    static const QRegularExpression listStart(
        QStringLiteral("^\\s*[•*\\-]\\s+"));

    const QStringList blocks = pageText.split(
        QRegularExpression(QStringLiteral("\\n\\s*\\n+")), Qt::SkipEmptyParts);
    QVector<PageElement> &elements = m_pageElements[page - 1];

    for (const QString &raw : blocks) {
        const QString block = raw.trimmed();
        if (block.isEmpty()) continue;

        if (block.startsWith(imagePrefix) && block.endsWith(tableSuffix)) {
            const QString encoded = block.mid(
                imagePrefix.size(), block.size() - imagePrefix.size() - tableSuffix.size());
            const QJsonDocument imageDoc = QJsonDocument::fromJson(
                QByteArray::fromBase64(encoded.toLatin1()));
            if (imageDoc.isObject()) {
                const QJsonObject object = imageDoc.object();
                PageElement element;
                element.kind = ElementKind::Image;
                element.imageData = QByteArray::fromBase64(
                    object.value("data").toString().toLatin1());
                element.imageSize = QSize(object.value("width").toInt(),
                                          object.value("height").toInt());
                if (!element.imageData.isEmpty()) elements.append(element);
                continue;
            }
        }

        if (block.startsWith(codePrefix) && block.endsWith(tableSuffix)) {
            const QString encoded = block.mid(
                codePrefix.size(), block.size() - codePrefix.size() - tableSuffix.size());
            const QString code = QString::fromUtf8(QByteArray::fromBase64(encoded.toLatin1()));
            PageElement element;
            element.kind = ElementKind::Code;
            element.groups.append(appendTextGroup(
                code, page, ElementKind::Code, false));
            if (!code.isEmpty()) elements.append(element);
            continue;
        }

        if (block.startsWith(tablePrefix) && block.endsWith(tableSuffix)) {
            const QString encoded = block.mid(
                tablePrefix.size(), block.size() - tablePrefix.size() - tableSuffix.size());
            const QJsonDocument tableDoc = QJsonDocument::fromJson(
                QByteArray::fromBase64(encoded.toLatin1()));
            if (tableDoc.isArray()) {
                PageElement element;
                element.kind = ElementKind::Table;
                for (const QJsonValue &rowValue : tableDoc.array()) {
                    const QJsonArray row = rowValue.toArray();
                    element.rowColumns.append(row.size());
                    for (const QJsonValue &cell : row) {
                        element.groups.append(appendTextGroup(
                            cell.toString(), page, ElementKind::Table, false));
                    }
                }
                if (!element.groups.isEmpty()) elements.append(element);
                continue;
            }
        }

        if (block.startsWith(tocPrefix) && block.endsWith(tableSuffix)) {
            const QString encoded = block.mid(
                tocPrefix.size(), block.size() - tocPrefix.size() - tableSuffix.size());
            const QJsonDocument tocDoc = QJsonDocument::fromJson(
                QByteArray::fromBase64(encoded.toLatin1()));
            if (tocDoc.isArray()) {
                PageElement element;
                element.kind = ElementKind::Toc;
                for (const QJsonValue &rowValue : tocDoc.array()) {
                    const QJsonObject row = rowValue.toObject();
                    element.tocNumbers.append(row.value("number").toString());
                    element.tocPages.append(row.value("page").toString());
                    element.tocLevels.append(row.value("level").toInt(0));
                    element.tocBold.append(row.value("bold").toInt(0));
                    element.groups.append(appendTextGroup(
                        row.value("title").toString(), page, ElementKind::Toc, false));
                }
                if (!element.groups.isEmpty()) elements.append(element);
                continue;
            }
        }

        if (block.startsWith("### ")) {
            PageElement element;
            element.kind = ElementKind::Heading;
            element.groups.append(appendTextGroup(
                block.mid(4).trimmed(), page, ElementKind::Heading, false));
            elements.append(element);
            continue;
        }

        const QStringList lines = block.split('\n', Qt::SkipEmptyParts);
        bool allList = !lines.isEmpty();
        for (const QString &line : lines) {
            if (!listStart.match(line).hasMatch()) {
                allList = false;
                break;
            }
        }

        if (allList) {
            PageElement element;
            element.kind = ElementKind::List;
            for (const QString &line : lines) {
                const QString item = line.trimmed().replace(listStart, QString()).trimmed();
                if (!item.isEmpty()) {
                    element.groups.append(appendTextGroup(
                        item, page, ElementKind::List, true));
                }
            }
            if (!element.groups.isEmpty()) elements.append(element);
            continue;
        }

        PageElement element;
        element.kind = ElementKind::Paragraph;
        element.groups.append(appendTextGroup(
            block, page, ElementKind::Paragraph, true));
        elements.append(element);
    }
}

QStringList SplitViewReader::splitOversizedBlock(const QString &block) const {
    static const QRegularExpression sentenceSplitter(
        QStringLiteral("(?<=[.!?])\\s+(?=[A-ZÀ-Ỹ0-9])"));
    const QStringList sentences = block.split(sentenceSplitter, Qt::SkipEmptyParts);
    if (sentences.size() <= 1) {
        QStringList result;
        QString text = block;
        while (text.size() > kMaxUnitChars) {
            int cut = text.lastIndexOf(' ', kMaxUnitChars);
            if (cut < kMaxUnitChars / 2) cut = kMaxUnitChars;
            result.append(text.left(cut).trimmed());
            text = text.mid(cut).trimmed();
        }
        if (!text.isEmpty()) result.append(text);
        return result;
    }

    QStringList chunks;
    QString current;
    for (const QString &sentence : sentences) {
        QString part = sentence.trimmed();
        while (part.size() > kMaxUnitChars) {
            if (!current.isEmpty()) {
                chunks.append(current.trimmed());
                current.clear();
            }
            int cut = part.lastIndexOf(' ', kMaxUnitChars);
            if (cut < kMaxUnitChars / 2) cut = kMaxUnitChars;
            chunks.append(part.left(cut).trimmed());
            part = part.mid(cut).trimmed();
        }
        const int extra = current.isEmpty() ? part.size() : part.size() + 1;
        if (!current.isEmpty() && current.size() + extra > kMaxUnitChars) {
            chunks.append(current.trimmed());
            current.clear();
        }
        if (!current.isEmpty()) current.append(' ');
        current.append(part);
    }
    if (!current.trimmed().isEmpty()) chunks.append(current.trimmed());
    return chunks;
}

void SplitViewReader::showPage(int page) {
    m_visiblePage = qBound(1, page, m_pageCount);
    m_cancelled = false;
    m_pageClock.restart();

    m_isSyncing = true;
    if (m_currentDoc.type == DocumentType::PDF) {
        m_leftStack->setCurrentWidget(m_pdfPageScroll);
        m_pdfPageImage = PdfExtractor::renderPageImage(
            m_currentDoc.filePath, m_visiblePage - 1, 4.0, m_currentDoc.password);
        updatePdfPageImage();
        m_pdfPageScroll->verticalScrollBar()->setValue(0);
        m_pdfPageScroll->horizontalScrollBar()->setValue(
            m_pdfPageScroll->horizontalScrollBar()->maximum() / 2);

        m_rightStack->setCurrentWidget(m_rightPdfScroll);
        m_translatedPdfImage = generateTranslatedPageImage(m_visiblePage, 3.0);
        updateTranslatedPdfPageImage();
        m_rightPdfScroll->verticalScrollBar()->setValue(0);
        m_rightPdfScroll->horizontalScrollBar()->setValue(
            m_rightPdfScroll->horizontalScrollBar()->maximum() / 2);
    } else {
        m_leftStack->setCurrentWidget(m_leftBrowser);
        renderSourceTextPage();
        m_leftBrowser->verticalScrollBar()->setValue(0);

        m_rightStack->setCurrentWidget(m_rightBrowser);
        m_rightBrowser->verticalScrollBar()->setValue(0);
    }
    m_isSyncing = false;

    m_previousBtn->setEnabled(m_visiblePage > 1);
    m_nextBtn->setEnabled(m_visiblePage < m_pageCount);
    {
        const QSignalBlocker blocker(m_pageSpin);
        m_pageSpin->setValue(m_visiblePage);
    }
    m_leftLabel->setText(
        QString("📄 GỐC — Trang %1/%2").arg(m_visiblePage).arg(m_pageCount));
    renderCurrentPage();

    if (m_translator && m_translator->isNmtReady()) {
        queuePagesAround(m_visiblePage);
    } else {
        updateProgressLabel();
    }
}

void SplitViewReader::resizeEvent(QResizeEvent *event) {
    QWidget::resizeEvent(event);
    if (m_leftStack && m_leftStack->currentWidget() == m_pdfPageScroll) {
        updatePdfPageImage();
    }
    if (m_rightStack && m_rightStack->currentWidget() == m_rightPdfScroll) {
        updateTranslatedPdfPageImage();
    }
}

void SplitViewReader::setZoomFactor(qreal factor) {
    m_zoomFactor = qBound(0.4, factor, 3.5);
    if (m_zoomLabel) {
        m_zoomLabel->setText(QString("%1%").arg(qRound(m_zoomFactor * 100)));
    }
    updatePdfPageImage();
    updateTranslatedPdfPageImage();
}

void SplitViewReader::zoomIn() {
    setZoomFactor(m_zoomFactor + 0.15);
}

void SplitViewReader::zoomOut() {
    setZoomFactor(m_zoomFactor - 0.15);
}

void SplitViewReader::fitWidth() {
    if (m_pdfPageImage.isNull()) return;
    const qreal availW = qMax(200, m_pdfPageScroll->viewport()->width() - 32);
    const qreal normalH = qMax(320, m_pdfPageScroll->viewport()->height() - 26);
    const qreal normalW = normalH * (static_cast<qreal>(m_pdfPageImage.width()) / m_pdfPageImage.height());
    if (normalW > 0) {
        setZoomFactor(availW / normalW);
    }
}

bool SplitViewReader::eventFilter(QObject *watched, QEvent *event) {
    if (watched == m_pdfPageScroll->viewport() || watched == m_rightPdfScroll->viewport() ||
        watched == m_pdfPageLabel || watched == m_rightPdfLabel) {

        if (event->type() == QEvent::Wheel) {
            auto *wheelEvent = static_cast<QWheelEvent *>(event);
            if (wheelEvent->modifiers() & Qt::ControlModifier) {
                if (wheelEvent->angleDelta().y() > 0) {
                    zoomIn();
                } else if (wheelEvent->angleDelta().y() < 0) {
                    zoomOut();
                }
                return true;
            }
        } else if (event->type() == QEvent::MouseButtonPress) {
            auto *mouseEvent = static_cast<QMouseEvent *>(event);
            if (mouseEvent->button() == Qt::MiddleButton || mouseEvent->button() == Qt::LeftButton) {
                m_isPanning = true;
                m_panStartPos = mouseEvent->globalPosition().toPoint();
                m_pdfPageScroll->viewport()->setCursor(Qt::ClosedHandCursor);
                m_rightPdfScroll->viewport()->setCursor(Qt::ClosedHandCursor);
                return true;
            }
        } else if (event->type() == QEvent::MouseMove && m_isPanning) {
            auto *mouseEvent = static_cast<QMouseEvent *>(event);
            QPoint delta = mouseEvent->globalPosition().toPoint() - m_panStartPos;
            m_panStartPos = mouseEvent->globalPosition().toPoint();

            m_pdfPageScroll->horizontalScrollBar()->setValue(m_pdfPageScroll->horizontalScrollBar()->value() - delta.x());
            m_pdfPageScroll->verticalScrollBar()->setValue(m_pdfPageScroll->verticalScrollBar()->value() - delta.y());
            m_rightPdfScroll->horizontalScrollBar()->setValue(m_rightPdfScroll->horizontalScrollBar()->value() - delta.x());
            m_rightPdfScroll->verticalScrollBar()->setValue(m_rightPdfScroll->verticalScrollBar()->value() - delta.y());
            return true;
        } else if (event->type() == QEvent::MouseButtonRelease && m_isPanning) {
            m_isPanning = false;
            m_pdfPageScroll->viewport()->setCursor(Qt::ArrowCursor);
            m_rightPdfScroll->viewport()->setCursor(Qt::ArrowCursor);
            return true;
        }
    }
    return QWidget::eventFilter(watched, event);
}

void SplitViewReader::updatePdfPageImage() {
    if (m_pdfPageImage.isNull()) {
        m_pdfPageLabel->setText("Không render được trang PDF gốc");
        m_pdfPageLabel->resize(420, 180);
        return;
    }
    const bool isLandscape = (m_pdfPageImage.width() > m_pdfPageImage.height());
    int targetWidth = 0;
    int targetHeight = 0;

    if (isLandscape) {
        targetWidth = qMax(300, qRound((m_pdfPageScroll->viewport()->width() - 28) * m_zoomFactor));
        targetHeight = qRound(targetWidth * (static_cast<qreal>(m_pdfPageImage.height()) / m_pdfPageImage.width()));
    } else {
        targetHeight = qMax(320, qRound((m_pdfPageScroll->viewport()->height() - 26) * m_zoomFactor));
        targetWidth = qRound(targetHeight * (static_cast<qreal>(m_pdfPageImage.width()) / m_pdfPageImage.height()));
    }

    const qreal pixelRatio = qMax<qreal>(1.0, m_pdfPageLabel->devicePixelRatioF());
    QPixmap pixmap = QPixmap::fromImage(m_pdfPageImage).scaled(
        qRound(targetWidth * pixelRatio), qRound(targetHeight * pixelRatio),
        Qt::KeepAspectRatio, Qt::SmoothTransformation);
    pixmap.setDevicePixelRatio(pixelRatio);
    m_pdfPageLabel->setText(QString());
    m_pdfPageLabel->setPixmap(pixmap);
    m_pdfPageLabel->resize(pixmap.deviceIndependentSize().toSize());
}

void SplitViewReader::updateTranslatedPdfPageImage() {
    if (m_translatedPdfImage.isNull()) {
        m_rightPdfLabel->setText("Đang chuẩn bị bản dịch trực quan...");
        m_rightPdfLabel->resize(420, 180);
        return;
    }
    const bool isLandscape = (m_translatedPdfImage.width() > m_translatedPdfImage.height());
    int targetWidth = 0;
    int targetHeight = 0;

    if (isLandscape) {
        targetWidth = qMax(300, qRound((m_rightPdfScroll->viewport()->width() - 28) * m_zoomFactor));
        targetHeight = qRound(targetWidth * (static_cast<qreal>(m_translatedPdfImage.height()) / m_translatedPdfImage.width()));
    } else {
        targetHeight = qMax(320, qRound((m_rightPdfScroll->viewport()->height() - 26) * m_zoomFactor));
        targetWidth = qRound(targetHeight * (static_cast<qreal>(m_translatedPdfImage.width()) / m_translatedPdfImage.height()));
    }

    const qreal pixelRatio = qMax<qreal>(1.0, m_rightPdfLabel->devicePixelRatioF());
    QPixmap pixmap = QPixmap::fromImage(m_translatedPdfImage).scaled(
        qRound(targetWidth * pixelRatio), qRound(targetHeight * pixelRatio),
        Qt::KeepAspectRatio, Qt::SmoothTransformation);
    pixmap.setDevicePixelRatio(pixelRatio);
    m_rightPdfLabel->setText(QString());
    m_rightPdfLabel->setPixmap(pixmap);
    m_rightPdfLabel->resize(pixmap.deviceIndependentSize().toSize());
}

QImage SplitViewReader::generateTranslatedPageImage(int pageIndex, qreal scale) {
    if (pageIndex < 1 || m_currentDoc.filePath.isEmpty()) return {};

    QImage baseImage = PdfExtractor::renderPageImage(m_currentDoc.filePath, pageIndex - 1, scale, m_currentDoc.password);
    if (baseImage.isNull()) return {};

    const int pageLayoutIdx = pageIndex - 1;
    if (pageLayoutIdx < 0 || pageLayoutIdx >= m_currentDoc.pageLayouts.size()) {
        return baseImage;
    }
    const PageLayoutData &layout = m_currentDoc.pageLayouts[pageLayoutIdx];
    if (layout.blocks.isEmpty() || layout.width <= 0 || layout.height <= 0) {
        return baseImage;
    }

    const qreal scaleX = static_cast<qreal>(baseImage.width()) / layout.width;
    const qreal scaleY = static_cast<qreal>(baseImage.height()) / layout.height;

    auto sampleBgColor = [&](const QRectF &rect) -> QColor {
        int xL = qBound(0, qRound(rect.left() + 2), baseImage.width() - 1);
        int xR = qBound(0, qRound(rect.right() - 2), baseImage.width() - 1);
        int yT = qBound(0, qRound(rect.top() + 2), baseImage.height() - 1);
        int yB = qBound(0, qRound(rect.bottom() - 2), baseImage.height() - 1);

        QColor c1 = baseImage.pixelColor(xL, yT);
        QColor c2 = baseImage.pixelColor(xR, yT);
        QColor c3 = baseImage.pixelColor(xL, yB);
        QColor c4 = baseImage.pixelColor(xR, yB);

        int avgR = (c1.red() + c2.red() + c3.red() + c4.red()) / 4;
        int avgG = (c1.green() + c2.green() + c3.green() + c4.green()) / 4;
        int avgB = (c1.blue() + c2.blue() + c3.blue() + c4.blue()) / 4;
        return QColor(avgR, avgG, avgB);
    };

    int startUnitIndex = 0;
    for (int i = 0; i < m_units.size(); ++i) {
        if (m_unitPages.value(i) == pageIndex) {
            startUnitIndex = i;
            break;
        }
    }

    QPainter painter(&baseImage);
    painter.setRenderHint(QPainter::Antialiasing, true);
    painter.setRenderHint(QPainter::TextAntialiasing, true);
    painter.setRenderHint(QPainter::SmoothPixmapTransform, true);

    for (int bIdx = 0; bIdx < layout.blocks.size(); ++bIdx) {
        const LayoutBlock &blk = layout.blocks[bIdx];
        if (blk.isWatermark) {
            // NEVER paint over watermark! The base image already has the original background watermark.
            continue;
        }
        if (blk.bbox.width() <= 0 || blk.bbox.height() <= 0) continue;

        int unitIdx = m_blockToUnit.value({pageLayoutIdx, bIdx}, -1);
        QString text = (unitIdx >= 0 && m_results.contains(unitIdx))
                       ? m_results.value(unitIdx)
                       : blk.text;

        // Clean any residual markdown markers
        while (text.startsWith("# ") || text.startsWith("## ") || text.startsWith("### ")) {
            int sp = text.indexOf(' ');
            text = text.mid(sp + 1).trimmed();
        }
        text.replace("**", "").replace("__", "").replace("`", "");
        text = text.trimmed();
        if (text.isEmpty()) continue;

        QRectF pixelRect(
            blk.bbox.x() * scaleX,
            blk.bbox.y() * scaleY,
            blk.bbox.width() * scaleX,
            blk.bbox.height() * scaleY
        );

        // Determine background and text colors
        bool isWhiteText = (blk.color == Qt::white || blk.color == QColor("#ffffff"));
        QColor bgColor;
        QColor penColor;

        if (isWhiteText) {
            QColor sampledBg = sampleBgColor(pixelRect);
            bgColor = (sampledBg.lightness() < 160) ? sampledBg : QColor("#185adb");
            penColor = QColor(255, 255, 255);
        } else {
            bgColor = QColor(255, 255, 255, 255);
            penColor = (blk.isHeading ? QColor("#0f172a") : QColor("#111827"));
        }

        // Clean erase original English text with background
        QRectF fillRect = pixelRect.adjusted(-1.5 * scaleX, -1.0 * scaleY, 1.5 * scaleX, 1.5 * scaleY);
        painter.fillRect(fillRect, bgColor);

        QFont font("Segoe UI");
        if (blk.isHeading) {
            font.setFamily("Georgia");
            font.setBold(true);
        } else if (blk.isBold) {
            font.setBold(true);
        }

        // Handle Rotated Text (e.g. 90 deg, -90 deg, 180 deg)
        if (blk.angle != 0) {
            painter.save();
            QPointF center = pixelRect.center();
            painter.translate(center);
            painter.rotate(blk.angle);

            qreal rad = qDegreesToRadians(static_cast<qreal>(blk.angle));
            qreal cosA = qAbs(qCos(rad));
            qreal origW = blk.bbox.width() * scaleX;
            qreal origH = blk.bbox.height() * scaleY;
            qreal rotWidth = (cosA > 0.01) ? qMax(origW, origH) : origH;
            qreal rotHeight = qMax(12.0 * scaleY, blk.fontSize * scaleY * 1.5);
            QRectF rotRect(-rotWidth / 2.0, -rotHeight / 2.0, rotWidth, rotHeight);

            qreal targetPixelSize = blk.fontSize * scaleY * 0.95;
            font.setPixelSize(qMax(8, qRound(targetPixelSize)));
            painter.setFont(font);
            painter.setPen(penColor);
            painter.drawText(rotRect, Qt::AlignCenter, text);
            painter.restore();
            continue;
        }

        // Standard Horizontal Text
        qreal targetPixelSize = blk.fontSize * scaleY * 0.92;
        font.setPixelSize(qMax(9, qRound(targetPixelSize)));

        // Test if text fits within bounding box height, adjust font size gently if needed
        QFontMetricsF fm(font);
        QRectF textBound = fm.boundingRect(pixelRect, Qt::TextWordWrap | Qt::AlignLeft | Qt::AlignTop, text);
        if (textBound.height() > pixelRect.height() * 1.05 && pixelRect.height() > 0) {
            qreal ratio = qBound(0.78, (pixelRect.height() * 1.0) / textBound.height(), 1.0);
            font.setPixelSize(qMax(8, qRound(targetPixelSize * ratio)));
        }

        painter.setFont(font);
        painter.setPen(penColor);

        // Add padding at bottom and right for Vietnamese accents and descenders
        QRectF drawRect = pixelRect.adjusted(0, 0, 2 * scaleX, 6 * scaleY);
        QTextOption textOption;
        textOption.setWrapMode(QTextOption::WrapAtWordBoundaryOrAnywhere);
        textOption.setAlignment(Qt::AlignLeft | Qt::AlignTop);

        painter.drawText(drawRect, text, textOption);
    }
    painter.end();

    return baseImage;
}

void SplitViewReader::renderSourceTextPage() {
    m_leftBrowser->setPlainText(m_pageTexts.value(m_visiblePage - 1));
}

void SplitViewReader::showPreviousPage() {
    showPage(m_visiblePage - 1);
}

void SplitViewReader::showNextPage() {
    showPage(m_visiblePage + 1);
}

void SplitViewReader::syncScrollLeft(int value) {
    if (m_isSyncing) return;
    m_isSyncing = true;
    QScrollBar *source = m_leftStack->currentWidget() == m_pdfPageScroll
        ? m_pdfPageScroll->verticalScrollBar()
        : m_leftBrowser->verticalScrollBar();
    QScrollBar *target = m_rightStack->currentWidget() == m_rightPdfScroll
        ? m_rightPdfScroll->verticalScrollBar()
        : m_rightBrowser->verticalScrollBar();
    const int mapped = source->maximum() > 0
        ? qRound(static_cast<double>(value) * target->maximum() / source->maximum()) : 0;
    target->setValue(mapped);
    m_isSyncing = false;
}

void SplitViewReader::syncScrollRight(int value) {
    if (m_isSyncing) return;
    m_isSyncing = true;
    QScrollBar *source = m_rightStack->currentWidget() == m_rightPdfScroll
        ? m_rightPdfScroll->verticalScrollBar()
        : m_rightBrowser->verticalScrollBar();
    QScrollBar *target = m_leftStack->currentWidget() == m_pdfPageScroll
        ? m_pdfPageScroll->verticalScrollBar()
        : m_leftBrowser->verticalScrollBar();
    const int mapped = source->maximum() > 0
        ? qRound(static_cast<double>(value) * target->maximum() / source->maximum()) : 0;
    target->setValue(mapped);
    m_isSyncing = false;
}

void SplitViewReader::queueAllPages(int priorityPage) {
    if (!m_translator || !m_translator->isNmtReady() || m_cancelled) return;

    QList<int> highPriority;
    QList<int> lowPriority;

    for (int idx = 0; idx < m_units.size(); ++idx) {
        if (m_results.contains(idx) || m_failedUnits.contains(idx)) continue;
        int page = m_unitPages.value(idx);
        int distance = qAbs(page - priorityPage);
        if (distance <= 1) {
            highPriority.append(idx);
        } else {
            lowPriority.append(idx);
        }
    }

    m_pendingUnits = highPriority + lowPriority;
    m_queuedUnits.clear();
    for (int idx : m_pendingUnits) {
        m_queuedUnits.insert(idx);
    }

    requestMoreTranslations();
}

void SplitViewReader::queuePagesAround(int page) {
    if (!m_translator || !m_translator->isNmtReady() || m_cancelled) return;

    // Promote the current page's units to the FRONT of pending queue without losing other background units
    QList<int> promoted;
    QList<int> rest;

    for (int unitIndex : m_pendingUnits) {
        int unitPage = m_unitPages.value(unitIndex);
        if (qAbs(unitPage - page) <= 1) {
            promoted.append(unitIndex);
        } else {
            rest.append(unitIndex);
        }
    }

    // Add any untranslated unit on this page that might not be in pending yet
    for (int idx = 0; idx < m_units.size(); ++idx) {
        if (m_unitPages.value(idx) == page && !m_results.contains(idx) &&
            !m_failedUnits.contains(idx) && !promoted.contains(idx)) {
            promoted.prepend(idx);
            m_queuedUnits.insert(idx);
        }
    }

    m_pendingUnits = promoted + rest;
    requestMoreTranslations();
}

void SplitViewReader::queuePage(int page, bool highPriority) {
    if (page < 1 || page > m_pageCount) return;
    for (int index = 0; index < m_units.size(); ++index) {
        if (m_unitPages.value(index) != page) continue;
        if (m_results.contains(index) || m_failedUnits.contains(index)
                || m_queuedUnits.contains(index)) {
            continue;
        }
        if (highPriority) {
            m_pendingUnits.prepend(index);
        } else {
            m_pendingUnits.append(index);
        }
        m_queuedUnits.insert(index);
    }
}

void SplitViewReader::requestMoreTranslations() {
    if (!m_translator || !m_translator->isNmtReady() || m_cancelled) return;

    while (m_inFlight < kMaxInFlight && !m_pendingUnits.isEmpty()) {
        const int unitIndex = m_pendingUnits.takeFirst();
        const QString text = m_units.value(unitIndex);

        if (shouldKeepOriginal(text)) {
            m_results.insert(unitIndex, text);
            m_polishedUnits.insert(unitIndex);
            m_queuedUnits.remove(unitIndex);
            m_renderTimer.start();
            continue;
        }

        const int reqId = m_nextRequestId++;
        m_requestToUnit.insert(reqId, unitIndex);
        ++m_inFlight;
        m_cancelBtn->setEnabled(true);
        m_translator->requestAsyncTranslation(reqId, text);
    }

    if (m_inFlight == 0 && m_pendingUnits.isEmpty()) {
        m_cancelBtn->setEnabled(false);
    }
    updateProgressLabel();
}

bool SplitViewReader::shouldKeepOriginal(const QString &text) const {
    const QString cleaned = text.trimmed();
    if (cleaned.isEmpty()) return true;
    if (isCodeBlock(cleaned)) return true;
    return isLikelyNonLinguistic(cleaned);
}

bool SplitViewReader::isCodeBlock(const QString &text) const {
    return text.contains("void ") || text.contains("class ") || text.contains("#include")
        || text.contains("public:") || text.contains("def ") || text.contains("import ");
}

bool SplitViewReader::isLikelyNonLinguistic(const QString &text) const {
    if (text.size() <= 4 && text.contains(QRegularExpression("^[0-9\\W]+$"))) {
        return true;
    }
    return false;
}

void SplitViewReader::onTranslationResultReady(int reqId, const QString &result) {
    if (!m_requestToUnit.contains(reqId)) return;
    const int unitIndex = m_requestToUnit.value(reqId);
    if (m_queuedUnits.contains(unitIndex)) {
        --m_inFlight;
        ++m_received;
        m_queuedUnits.remove(unitIndex);
    }
    m_results.insert(unitIndex, result);

    if (m_unitPages.value(unitIndex) == m_visiblePage) {
        m_renderTimer.start();
    }
    updateProgressLabel();
    requestMoreTranslations();
}

void SplitViewReader::onTranslationPolishedReady(int reqId, const QString &result) {
    if (!m_requestToUnit.contains(reqId)) return;
    const int unitIndex = m_requestToUnit.value(reqId);
    m_results.insert(unitIndex, result);
    m_polishedUnits.insert(unitIndex);

    if (m_unitPages.value(unitIndex) == m_visiblePage) {
        m_renderTimer.start();
    }
    updateProgressLabel();
}

void SplitViewReader::onTranslationFailed(int reqId, const QString &error) {
    if (!m_requestToUnit.contains(reqId)) return;
    const int unitIndex = m_requestToUnit.take(reqId);
    --m_inFlight;
    m_queuedUnits.remove(unitIndex);
    m_failedUnits.insert(unitIndex);

    m_results.insert(unitIndex, m_units.value(unitIndex));
    m_polishedUnits.insert(unitIndex);
    if (m_unitPages.value(unitIndex) == m_visiblePage) {
        m_renderTimer.start();
    }
    requestMoreTranslations();
}

void SplitViewReader::onNmtProcessFailed(const QString &error) {
    qWarning() << "NMT process failed:" << error;
    updateProgressLabel();
}

void SplitViewReader::resumeOrRestartModels() {
    if (!m_translator) return;

    const bool nmtCrashed = (m_translator->nmtStatus() == OfflineTranslator::ModelStatus::Crashed || !m_translator->isNmtReady());
    const bool polishCrashed = (m_translator->polishStatus() == OfflineTranslator::ModelStatus::Crashed);

    m_cancelled = false;
    m_cancelBtn->setEnabled(true);

    // 1. Restart models if stopped or crashed
    if (nmtCrashed) {
        m_translator->restartDaemon();
    } else if (polishCrashed) {
        m_translator->restartPolishModel();
    }

    // 2. Identify unfinished parts and re-queue them
    int requeuedRaw = 0;
    int requeuedPolish = 0;

    QList<int> pendingRawList;
    QList<int> pendingPolishList;

    for (int i = 0; i < m_units.size(); ++i) {
        if (!m_results.contains(i)) {
            m_failedUnits.remove(i);
            m_queuedUnits.remove(i);
            if (m_unitPages.value(i) == m_visiblePage) {
                pendingRawList.prepend(i);
            } else {
                pendingRawList.append(i);
            }
            requeuedRaw++;
        } else if (!m_polishedUnits.contains(i)) {
            m_failedUnits.remove(i);
            if (m_unitPages.value(i) == m_visiblePage) {
                pendingPolishList.prepend(i);
            } else {
                pendingPolishList.append(i);
            }
            requeuedPolish++;
        }
    }

    for (int u : pendingRawList) {
        if (!m_pendingUnits.contains(u)) {
            m_pendingUnits.append(u);
        }
    }

    // Direct polish for units that already have raw translations
    if (!pendingPolishList.isEmpty() && m_translator->isPolishAvailable()) {
        for (int u : pendingPolishList) {
            const int reqId = m_nextRequestId++;
            m_requestToUnit.insert(reqId, u);
            m_translator->requestPolishOnlyAsync(reqId, m_units.value(u), m_results.value(u));
        }
    }

    qDebug() << "resumeOrRestartModels: Requeued" << requeuedRaw << "raw and" << requeuedPolish << "polish units";
    requestMoreTranslations();
    updateProgressLabel();
}

void SplitViewReader::cancelTranslation() {
    m_cancelled = true;
    m_pendingUnits.clear();
    m_queuedUnits.clear();
    if (m_translator) m_translator->cancelQueuedTranslations();
    m_cancelBtn->setEnabled(false);
    updateProgressLabel();
}

void SplitViewReader::clearCache() {
    if (QMessageBox::question(this, "Xác nhận xóa Cache",
        "Bạn có chắc chắn muốn xóa toàn bộ bộ nhớ đệm bản dịch không?\n"
        "Toàn bộ tài liệu sẽ được dịch lại từ đầu bằng GPU.",
        QMessageBox::Yes | QMessageBox::No) != QMessageBox::Yes) {
        return;
    }
    if (m_translator) {
        m_translator->clearCache();
    }
    m_results.clear();
    m_failedUnits.clear();
    m_polishedUnits.clear();
    m_pendingUnits.clear();
    m_queuedUnits.clear();
    m_requestToUnit.clear();
    m_inFlight = 0;
    m_received = 0;
    m_cancelled = false;
    queueAllPages(m_visiblePage);
    renderCurrentPage();
    updateProgressLabel();
}

bool SplitViewReader::isPageComplete(int page) const {
    for (int index = 0; index < m_units.size(); ++index) {
        if (m_unitPages.value(index) != page) continue;
        if (!m_results.contains(index) && !m_failedUnits.contains(index)) {
            return false;
        }
    }
    return true;
}

QString SplitViewReader::renderGroup(const QVector<int> &group) const {
    QStringList parts;
    for (int index : group) {
        if (m_results.contains(index)) {
            parts.append(m_results.value(index));
        } else {
            parts.append(m_units.value(index));
        }
    }
    return parts.join(" ").toHtmlEscaped();
}

void SplitViewReader::updateProgressLabel() {
    OfflineTranslator::ModelStatus nmtSt = m_translator ? m_translator->nmtStatus() : OfflineTranslator::ModelStatus::NotStarted;
    OfflineTranslator::ModelStatus polSt = m_translator ? m_translator->polishStatus() : OfflineTranslator::ModelStatus::NotStarted;

    const bool nmtCrashed = (nmtSt == OfflineTranslator::ModelStatus::Crashed);
    const bool polishCrashed = (polSt == OfflineTranslator::ModelStatus::Crashed);
    const bool anyCrashed = nmtCrashed || polishCrashed;

    const int docTotal = m_units.size();
    const int docRawDone = m_results.size();
    const int docPolishedDone = m_polishedUnits.size();

    // 1. Manage Restart/Resume button state
    if (m_restartBtn) {
        if (anyCrashed) {
            m_restartBtn->setVisible(true);
            m_restartBtn->setText("⚡ Bật lại Model & Tiếp tục");
            m_restartBtn->setStyleSheet(
                "QPushButton { background:#c62828; color:#ffffff; font-weight:700; font-size:11px; "
                "border:1px solid #ef5350; border-radius:5px; padding:4px 10px; }"
                "QPushButton:hover { background:#d32f2f; }"
            );
        } else if (m_cancelled && (docRawDone < docTotal || docPolishedDone < docTotal)) {
            m_restartBtn->setVisible(true);
            m_restartBtn->setText("▶ Tiếp tục dịch");
            m_restartBtn->setStyleSheet(
                "QPushButton { background:#0277bd; color:#ffffff; font-weight:700; font-size:11px; "
                "border:1px solid #29b6f6; border-radius:5px; padding:4px 10px; }"
                "QPushButton:hover { background:#0288d1; }"
            );
        } else {
            m_restartBtn->setVisible(false);
        }
    }

    // 2. Build Badges for Model 1 & Model 2
    QString vinaiBadge;
    if (nmtCrashed) {
        vinaiBadge = QString(
            "<span style='background:#450a0a; color:#f87171; border:1px solid #dc2626; "
            "padding:3px 8px; border-radius:5px; font-weight:700; font-size:11px;'>"
            "❌ VinAI: CRASH / DỪNG</span>"
        );
    } else if (nmtSt == OfflineTranslator::ModelStatus::Loading || !m_translator || !m_translator->isNmtReady()) {
        vinaiBadge = QString(
            "<span style='background:#78350f; color:#fde68a; border:1px solid #f59e0b; "
            "padding:3px 8px; border-radius:5px; font-weight:700; font-size:11px;'>"
            "⏳ VinAI: Đang nạp...</span>"
        );
    } else {
        const int rawPercent = docTotal > 0 ? qMin(100, (docRawDone * 100 / docTotal)) : 100;
        if (docTotal > 0 && docRawDone >= docTotal) {
            vinaiBadge = QString(
                "<span style='background:#064e3b; color:#34d399; border:1px solid #059669; "
                "padding:3px 8px; border-radius:5px; font-weight:700; font-size:11px;'>"
                "⚡ VinAI: 100% Hoàn tất</span>"
            );
        } else {
            vinaiBadge = QString(
                "<span style='background:#102a43; color:#4ade80; border:1px solid #1e3a5f; "
                "padding:3px 8px; border-radius:5px; font-weight:700; font-size:11px;'>"
                "⚡ VinAI: %1% (%2/%3)</span>"
            ).arg(rawPercent).arg(docRawDone).arg(docTotal);
        }
    }

    QString vyLinhBadge;
    if (polishCrashed) {
        vyLinhBadge = QString(
            "<span style='background:#450a0a; color:#f87171; border:1px solid #dc2626; "
            "padding:3px 8px; border-radius:5px; font-weight:700; font-size:11px;'>"
            "❌ VyLinh: CRASH / DỪNG</span>"
        );
    } else if (polSt == OfflineTranslator::ModelStatus::Loading) {
        vyLinhBadge = QString(
            "<span style='background:#3b0764; color:#d8b4fe; border:1px solid #7e22ce; "
            "padding:3px 8px; border-radius:5px; font-weight:700; font-size:11px;'>"
            "⏳ VyLinh: Đang tải...</span>"
        );
    } else if (!m_translator || !m_translator->isPolishAvailable()) {
        vyLinhBadge = QString(
            "<span style='background:#27272a; color:#a1a1aa; border:1px solid #3f3f46; "
            "padding:3px 8px; border-radius:5px; font-weight:600; font-size:11px;'>"
            "✨ VyLinh: Tắt</span>"
        );
    } else if (docPolishedDone >= docTotal && docTotal > 0) {
        vyLinhBadge = QString(
            "<span style='background:#064e3b; color:#34d399; border:1px solid #059669; "
            "padding:3px 8px; border-radius:5px; font-weight:700; font-size:11px;'>"
            "✨ VyLinh Polish: 100% Hoàn tất</span>"
        );
    } else {
        const int polishPercent = docTotal > 0 ? qMin(100, (docPolishedDone * 100 / docTotal)) : 100;
        vyLinhBadge = QString(
            "<span style='background:#2e1065; color:#c084fc; border:1px solid #581c87; "
            "padding:3px 8px; border-radius:5px; font-weight:700; font-size:11px;'>"
            "✨ VyLinh Polish: %1% (%2/%3) ⏳</span>"
        ).arg(polishPercent).arg(docPolishedDone).arg(docTotal);
    }

    int pageTotal = 0;
    int pagePolishedDone = 0;
    for (int index = 0; index < m_units.size(); ++index) {
        if (m_unitPages.value(index) != m_visiblePage) continue;
        ++pageTotal;
        if (m_polishedUnits.contains(index)) ++pagePolishedDone;
    }

    QString statusSuffix;
    if (anyCrashed) {
        statusSuffix = "<span style='color:#ef5350; font-size:11px; font-weight:700;'>⚠️ Nhấn nút đỏ để Bật lại & Tiếp tục</span>";
    } else if (m_cancelled) {
        statusSuffix = "<span style='color:#90a4ae; font-size:11px; font-weight:700;'>⏹ Đã dừng</span>";
    } else if (docTotal > 0 && docRawDone >= docTotal && docPolishedDone >= docTotal) {
        statusSuffix = "<span style='color:#00e676; font-size:11px; font-weight:700;'>✨ Đã dịch & trau chuốt hoàn tất</span>";
        m_cancelBtn->setEnabled(false);
    } else {
        statusSuffix = QString(
            "<span style='color:#94a3b8; font-size:11px; font-weight:600;'>"
            "Trang %1: %2/%3 trau chuốt</span>"
        ).arg(m_visiblePage).arg(pagePolishedDone).arg(pageTotal);
    }

    m_rightLabel->setText(QString("%1  %2  %3").arg(vinaiBadge, vyLinhBadge, statusSuffix));
    m_rightLabel->setStyleSheet("background:transparent;");
}

void SplitViewReader::renderCurrentPage() {
    if (m_currentDoc.type == DocumentType::PDF) {
        m_rightStack->setCurrentWidget(m_rightPdfScroll);
        m_translatedPdfImage = generateTranslatedPageImage(m_visiblePage, 3.0);
        updateTranslatedPdfPageImage();
        updateProgressLabel();
        return;
    }

    m_rightStack->setCurrentWidget(m_rightBrowser);
    QScrollBar *scroll = m_rightBrowser->verticalScrollBar();
    const double scrollRatio = scroll->maximum() > 0
        ? static_cast<double>(scroll->value()) / scroll->maximum() : 0.0;

    QString html = QStringLiteral(
        "<div style='color:#24272b;font-size:15px;line-height:1.58;"
        "font-family:-apple-system,BlinkMacSystemFont,"
        "\"SF Pro Text\",sans-serif;'>");
    const QVector<PageElement> elements = m_pageElements.value(m_visiblePage - 1);
    for (const PageElement &element : elements) {
        if (element.kind == ElementKind::Heading) {
            html.append(QString(
                "<h3 style='margin:20px 0 9px;color:#175ea8;font-size:20px;"
                "border-bottom:1px solid #d9e2ec;padding-bottom:5px;'>%1</h3>")
                .arg(renderGroup(element.groups.value(0))));
        } else if (element.kind == ElementKind::Paragraph) {
            html.append(QString(
                "<p style='margin:0 0 14px;font-size:15px;'>%1</p>")
                .arg(renderGroup(element.groups.value(0))));
        } else if (element.kind == ElementKind::List) {
            html.append("<ul style='margin:5px 0 14px;padding-left:22px;'>");
            for (const QVector<int> &group : element.groups) {
                html.append(QString("<li style='margin:4px 0;'>%1</li>")
                    .arg(renderGroup(group)));
            }
            html.append("</ul>");
        } else if (element.kind == ElementKind::Code) {
            html.append(QString(
                "<pre style='margin:8px 0 14px;background:#f2f4f7;color:#344054;"
                "border:1px solid #d0d5dd;padding:10px;font-family:Menlo,monospace;"
                "font-size:12px;white-space:pre-wrap;'>%1</pre>")
                .arg(renderGroup(element.groups.value(0))));
        }
    }
    if (elements.isEmpty()) {
        html.append("<div style='padding:24px;color:#777;'>Trang này không có text để dịch.</div>");
    }
    html.append("</div>");

    m_isSyncing = true;
    m_rightBrowser->setHtml(html);
    scroll->setValue(qRound(scrollRatio * scroll->maximum()));
    m_isSyncing = false;
    updateProgressLabel();
}

void SplitViewReader::exportTranslatedPdf() {
    if (m_currentDoc.filePath.isEmpty() || m_pageCount <= 0) {
        QMessageBox::warning(this, "Thông báo", "Không có tài liệu nào đang mở để xuất.");
        return;
    }

    QString defaultName = QFileInfo(m_currentDoc.filePath).completeBaseName() + "_translated.pdf";
    QString exportPath = QFileDialog::getSaveFileName(
        this,
        "Xuất Tài Liệu PDF Đã Dịch",
        defaultName,
        "Tệp PDF (*.pdf)"
    );
    if (exportPath.isEmpty()) return;

    QProgressDialog progress("Đang xuất tài liệu PDF...", "Hủy", 0, m_pageCount, this);
    progress.setWindowTitle("Xuất PDF Đã Dịch");
    progress.setWindowModality(Qt::WindowModal);
    progress.setMinimumDuration(0);
    progress.setValue(0);

    QPdfWriter writer(exportPath);
    writer.setResolution(300);

    QPainter painter;
    if (!painter.begin(&writer)) {
        QMessageBox::critical(this, "Lỗi", "Không thể tạo tệp PDF tại đường dẫn đã chọn. Vui lòng kiểm tra quyền ghi tệp.");
        return;
    }

    for (int page = 1; page <= m_pageCount; ++page) {
        progress.setLabelText(QString("Đang xuất trang %1 / %2...").arg(page).arg(m_pageCount));
        progress.setValue(page - 1);
        QCoreApplication::processEvents();

        if (progress.wasCanceled()) {
            painter.end();
            QFile::remove(exportPath);
            return;
        }

        if (page > 1) {
            writer.newPage();
        }

        if (m_currentDoc.type == DocumentType::PDF) {
            if (page - 1 < m_currentDoc.pageLayouts.size()) {
                const PageLayoutData &layout = m_currentDoc.pageLayouts[page - 1];
                if (layout.width > 0 && layout.height > 0) {
                    QPageSize pageSize(QSizeF(layout.width, layout.height), QPageSize::Point);
                    writer.setPageSize(pageSize);
                    writer.setPageMargins(QMarginsF(0, 0, 0, 0));
                }
            }
            QImage pageImg = generateTranslatedPageImage(page, 3.0);
            if (!pageImg.isNull()) {
                QRect targetRect = writer.pageLayout().paintRectPixels(writer.resolution());
                painter.drawImage(targetRect, pageImg);
            }
        } else {
            writer.setPageSize(QPageSize(QPageSize::A4));
            writer.setPageMargins(QMarginsF(15, 15, 15, 15), QPageLayout::Millimeter);
            QString pageTxt = m_pageTexts.value(page - 1);
            QRect targetRect = writer.pageLayout().paintRectPixels(writer.resolution());
            QFont printFont("Segoe UI", 11);
            painter.setFont(printFont);
            painter.setPen(Qt::black);
            painter.drawText(targetRect, Qt::TextWordWrap, pageTxt);
        }
    }

    painter.end();
    progress.setValue(m_pageCount);

    auto reply = QMessageBox::question(
        this,
        "Xuất Thành Công",
        "Đã xuất tài liệu PDF đã dịch thành công!\nĐường dẫn: " + exportPath + "\n\nBạn có muốn mở tệp ngay không?",
        QMessageBox::Yes | QMessageBox::No
    );
    if (reply == QMessageBox::Yes) {
        QDesktopServices::openUrl(QUrl::fromLocalFile(exportPath));
    }
}
