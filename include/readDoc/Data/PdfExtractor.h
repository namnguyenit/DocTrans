#ifndef PDFEXTRACTOR_H
#define PDFEXTRACTOR_H

#include <QImage>
#include <QString>
#include <QStringList>
#include <QRectF>
#include <QList>

#include <QColor>

struct LayoutBlock {
    int id = 0;
    QRectF bbox;
    QString text;
    qreal fontSize = 12.0;
    QColor color = Qt::black;
    int angle = 0;
    bool isHeading = false;
    bool isBold = false;
    bool isWatermark = false;
};

struct PageLayoutData {
    int pageIndex = 0;
    qreal width = 595.0;
    qreal height = 842.0;
    QString text;
    QList<LayoutBlock> blocks;
};

class PdfExtractor {
public:
    static bool isPasswordRequired(const QString &pdfPath);
    static bool verifyPassword(const QString &pdfPath, const QString &password);

    static QString extractText(const QString &pdfPath, const QString &password = QString());
    static QStringList extractPages(const QString &pdfPath, const QString &password = QString());
    static QList<PageLayoutData> extractLayouts(const QString &pdfPath, const QString &password = QString());
    static PageLayoutData extractPageLayout(const QString &pdfPath, int pageIndex, const QString &password = QString());
    static QString extractHtml(const QString &pdfPath);
    static QImage renderPageImage(const QString &pdfPath, int pageIndex,
                                  qreal scale = 4.0, const QString &password = QString());
};

#endif // PDFEXTRACTOR_H
