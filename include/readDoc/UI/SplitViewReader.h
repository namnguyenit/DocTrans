#pragma once

#include <QElapsedTimer>
#include <QHash>
#include <QImage>
#include <QLabel>
#include <QList>
#include <QPushButton>
#include <QScrollArea>
#include <QSet>
#include <QSpinBox>
#include <QSplitter>
#include <QStackedWidget>
#include <QTextBrowser>
#include <QTimer>
#include <QVector>
#include <QWidget>

#include "readDoc/Data/DocumentParser.h"
#include "readDoc/System/OfflineTranslator.h"

class SplitViewReader : public QWidget {
    Q_OBJECT
public:
    explicit SplitViewReader(OfflineTranslator *translator, QWidget *parent = nullptr);
    ~SplitViewReader();

    void loadDocument(const DocumentContent &doc);
    void goToPage(int page);

protected:
    void resizeEvent(QResizeEvent *event) override;

private slots:
    void syncScrollLeft(int value);
    void syncScrollRight(int value);
    void onNmtReady();
    void onPolishModelReady();
    void onTranslationResultReady(int reqId, const QString &result);
    void onTranslationPolishedReady(int reqId, const QString &result);
    void onTranslationFailed(int reqId, const QString &error);
    void onNmtProcessFailed(const QString &error);
    void cancelTranslation();
    void clearCache();
    void showPreviousPage();
    void showNextPage();
    void exportTranslatedPdf();
    void resumeOrRestartModels();
    void onModelStatusChanged();

private:
    QSplitter         *m_splitter = nullptr;
    QStackedWidget    *m_leftStack = nullptr;
    QStackedWidget    *m_rightStack = nullptr;
    QScrollArea       *m_pdfPageScroll = nullptr;
    QScrollArea       *m_rightPdfScroll = nullptr;
    QLabel            *m_pdfPageLabel = nullptr;
    QLabel            *m_rightPdfLabel = nullptr;
    QTextBrowser      *m_leftBrowser = nullptr;
    QTextBrowser      *m_rightBrowser = nullptr;
    
    OfflineTranslator *m_translator = nullptr;
    DocumentContent    m_currentDoc;

    QWidget     *m_headerBar = nullptr;
    QLabel      *m_leftLabel = nullptr;
    QLabel      *m_rightLabel = nullptr;
    QPushButton *m_zoomOutBtn = nullptr;
    QLabel      *m_zoomLabel = nullptr;
    QPushButton *m_zoomInBtn = nullptr;
    QPushButton *m_fitWidthBtn = nullptr;
    QPushButton *m_previousBtn = nullptr;
    QPushButton *m_nextBtn = nullptr;
    QSpinBox    *m_pageSpin = nullptr;
    QPushButton *m_exportPdfBtn = nullptr;
    QPushButton *m_cancelBtn = nullptr;
    QPushButton *m_restartBtn = nullptr;
    QPushButton *m_clearCacheBtn = nullptr;
    bool         m_isSyncing = false;
    qreal        m_zoomFactor = 1.0;
    bool         m_isPanning = false;
    QPoint       m_panStartPos;
    QImage       m_pdfPageImage;
    QImage       m_translatedPdfImage;

    enum class ElementKind { Heading, Paragraph, List, Code, Table, Image, Toc };
    struct PageElement {
        ElementKind kind = ElementKind::Paragraph;
        QVector<QVector<int>> groups;
        QVector<int> rowColumns;
        QStringList tocNumbers;
        QStringList tocPages;
        QVector<int> tocLevels;
        QVector<int> tocBold;
        QByteArray imageData;
        QSize imageSize;
    };

    QStringList m_pageTexts;
    QStringList m_units;
    QVector<int> m_unitPages;
    QVector<ElementKind> m_unitKinds;
    QVector<QVector<PageElement>> m_pageElements;
    QHash<int, QString> m_results;
    QSet<int> m_failedUnits;
    QSet<int> m_polishedUnits;
    QMap<QPair<int, int>, int> m_blockToUnit;

    QList<int> m_pendingUnits;
    QSet<int> m_queuedUnits;
    QHash<int, int> m_requestToUnit;
    int m_nextRequestId = 1;
    int m_inFlight = 0;
    int m_received = 0;

    int m_pageCount = 1;
    int m_visiblePage = 1;
    bool m_cancelled = false;

    QTimer m_renderTimer;
    QElapsedTimer m_pageClock;

    static constexpr int kMaxInFlight = 256;
    static constexpr int kVirtualPageChars = 5000;
    static constexpr int kMaxUnitChars = 300;

    void buildPagesAndUnits(const DocumentContent &doc);
    void buildPageElements(const QString &pageText, int page);
    QVector<int> appendTextGroup(const QString &text, int page,
                                 ElementKind kind, bool splitLong = true);
    QStringList splitOversizedBlock(const QString &block) const;
    void showPage(int page);
    void updatePdfPageImage();
    void updateTranslatedPdfPageImage();
    QImage generateTranslatedPageImage(int pageIndex, qreal scale = 3.0);
    void renderSourceTextPage();
    void queueAllPages(int priorityPage);
    void queuePagesAround(int page);
    void queuePage(int page, bool highPriority);
    void requestMoreTranslations();
    bool isPageComplete(int page) const;
    bool isLikelyNonLinguistic(const QString &text) const;
    bool shouldKeepOriginal(const QString &text) const;
    bool isCodeBlock(const QString &text) const;
    QString renderGroup(const QVector<int> &group) const;
    void updateProgressLabel();
    void renderCurrentPage();
    void setZoomFactor(qreal factor);
    void zoomIn();
    void zoomOut();
    void fitWidth();
    bool eventFilter(QObject *watched, QEvent *event) override;
};
