#pragma once

#include <QString>
#include <QStringList>
#include <QFileInfo>
#include <QList>
#include "readDoc/Data/PdfExtractor.h"

enum class DocumentType {
    PDF,
    DOCX,
    TXT,
    MARKDOWN,
    IMAGE,
    UNKNOWN
};

struct DocumentContent {
    QString filePath;
    QString fileName;
    DocumentType type;
    QString plainText;
    QString htmlContent;
    QStringList pageTexts;
    QList<PageLayoutData> pageLayouts;
    int pageCount = 1;
    QString password;
};

class DocumentParser {
public:
    static DocumentType detectType(const QString &filePath);
    static DocumentContent parseDocument(const QString &filePath, const QString &password = QString());

private:
    static QString parseTxt(const QString &filePath);
    static QString parseMarkdown(const QString &filePath);
    static QString parseMarkdownString(const QString &raw);
    static QString parseDocx(const QString &filePath);
};
