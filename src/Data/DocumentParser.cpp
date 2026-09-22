#include "readDoc/Data/DocumentParser.h"
#include "readDoc/Data/PdfExtractor.h"
#include <QFile>
#include <QTextStream>
#include <QRegularExpression>
#include <QProcess>

DocumentType DocumentParser::detectType(const QString &filePath) {
    QFileInfo info(filePath);
    QString ext = info.suffix().toLower();

    if (ext == "pdf") return DocumentType::PDF;
    if (ext == "docx") return DocumentType::DOCX;
    if (ext == "txt" || ext == "log") return DocumentType::TXT;
    if (ext == "md" || ext == "markdown") return DocumentType::MARKDOWN;
    if (ext == "png" || ext == "jpg" || ext == "jpeg" || ext == "webp" || ext == "bmp") return DocumentType::IMAGE;

    return DocumentType::UNKNOWN;
}

QString DocumentParser::parseTxt(const QString &filePath) {
    QFile f(filePath);
    if (!f.open(QIODevice::ReadOnly | QIODevice::Text)) return "";
    QTextStream in(&f);
    return in.readAll();
}

QString DocumentParser::parseMarkdown(const QString &filePath) {
    return parseMarkdownString(parseTxt(filePath));
}

QString DocumentParser::parseMarkdownString(const QString &raw) {
    if (raw.isEmpty()) return "";

    // Convert basic Markdown elements to HTML locally
    QString html = raw;
    html.replace("&", "&amp;");
    html.replace("<", "&lt;");
    html.replace(">", "&gt;");

    // Code blocks
    html.replace(QRegularExpression("```\\s*(.*?)\\s*```", QRegularExpression::DotMatchesEverythingOption), "<pre style='background: #1a1a1a; color: #00e676; padding: 10px; border-radius: 4px; font-family: monospace;'>\\1</pre>");

    // Headers
    html.replace(QRegularExpression("^# (.*)$", QRegularExpression::MultilineOption), "<h1>\\1</h1>");
    html.replace(QRegularExpression("^## (.*)$", QRegularExpression::MultilineOption), "<h2>\\1</h2>");
    html.replace(QRegularExpression("^### (.*)$", QRegularExpression::MultilineOption), "<h3 style='color: #4a9eff; margin-top: 16px; border-bottom: 1px solid rgba(74,158,255,0.2);'>\\1</h3>");

    // Bold & Italic
    html.replace(QRegularExpression("\\*\\*(.*?)\\*\\*"), "<b>\\1</b>");
    html.replace(QRegularExpression("\\*(.*?)\\*"), "<i>\\1</i>");

    // Line breaks
    html.replace("\n", "<br>");

    return html;
}

QString DocumentParser::parseDocx(const QString &filePath) {
    QProcess process;
#ifdef Q_OS_WIN
    process.start("tar", QStringList() << "-O" << "-xf" << filePath << "word/document.xml");
#else
    process.start("unzip", QStringList() << "-p" << filePath << "word/document.xml");
#endif
    process.waitForFinished();
    
    if (process.exitCode() != 0) {
        return "Failed to read DOCX file. Is it a valid Word document?";
    }
    
    QByteArray xmlData = process.readAllStandardOutput();
    QString xmlStr = QString::fromUtf8(xmlData);
    
    // Simple regex to extract text inside <w:t> tags
    QString text;
    QRegularExpression re("<w:t[^>]*>(.*?)</w:t>");
    QRegularExpressionMatchIterator i = re.globalMatch(xmlStr);
    
    // Also we need to handle paragraph breaks <w:p>
    // A slightly better approach is to split by <w:p> first, but simple <w:t> concatenation with spaces works
    // Let's replace <w:p> with newline to preserve paragraphs
    xmlStr.replace(QRegularExpression("<w:p[^>]*>"), "\n");
    i = re.globalMatch(xmlStr);
    
    int lastIndex = 0;
    while (i.hasNext()) {
        QRegularExpressionMatch match = i.next();
        QString snippet = match.captured(1);
        // If there was a newline between last match and this match, append newline
        int matchStart = match.capturedStart();
        if (xmlStr.mid(lastIndex, matchStart - lastIndex).contains('\n')) {
            text.append("\n");
        }
        text.append(snippet);
        lastIndex = match.capturedEnd();
    }
    
    text.replace(QRegularExpression("\n+"), "\n");
    return text.trimmed();
}

DocumentContent DocumentParser::parseDocument(const QString &filePath, const QString &password) {
    DocumentContent doc;
    doc.filePath = filePath;
    doc.password = password;
    QFileInfo info(filePath);
    doc.fileName = info.fileName();
    doc.type = detectType(filePath);

    switch (doc.type) {
        case DocumentType::TXT:
            doc.plainText = parseTxt(filePath);
            doc.htmlContent = "<pre style='font-family: inherit; font-size: 14px; line-height: 1.6; white-space: pre-wrap;'>" + doc.plainText.toHtmlEscaped() + "</pre>";
            break;

        case DocumentType::MARKDOWN:
            doc.plainText = parseTxt(filePath);
            doc.htmlContent = parseMarkdown(filePath);
            break;

        case DocumentType::DOCX:
            doc.plainText = parseDocx(filePath);
            doc.htmlContent = "<pre style='font-family: inherit; font-size: 14px; line-height: 1.6; white-space: pre-wrap;'>" + doc.plainText.toHtmlEscaped() + "</pre>";
            break;

        case DocumentType::PDF: {
            doc.pageLayouts = PdfExtractor::extractLayouts(filePath, password);
            doc.pageTexts.clear();
            doc.pageTexts.reserve(doc.pageLayouts.size());
            for (const auto &layout : doc.pageLayouts) {
                doc.pageTexts.append(layout.text);
            }
            doc.pageCount = qMax(1, doc.pageTexts.size());
            QStringList markedPages;
            markedPages.reserve(doc.pageTexts.size());
            for (int index = 0; index < doc.pageTexts.size(); ++index) {
                markedPages.append(doc.pageTexts[index] +
                                   QString("\n\n— TRANG %1 —").arg(index + 1));
            }
            doc.plainText = markedPages.join("\n\n");
            if (doc.plainText.isEmpty() || doc.plainText.startsWith("Error")) {
                doc.plainText = "PDF Document: " + doc.fileName + "\nFailed to extract text.";
                doc.htmlContent = "<div style='text-align:center; padding: 40px;'><h2>" + doc.fileName + "</h2><p>Không thể đọc nội dung file PDF.</p></div>";
            } else {
                // A flattened text rendition cannot preserve PDF columns, figures or tables.
                // ReaderWidget displays the original local PDF; pageTexts feed bilingual mode.
                doc.htmlContent.clear();
            }
            break;
        }

        case DocumentType::IMAGE:
            doc.plainText = "Image: " + doc.fileName;
            doc.htmlContent = "<div style='text-align:center; padding: 20px;'><img src='file://" + filePath + "' style='max-width: 100%; height: auto; border-radius: 8px;'></div>";
            break;

        default:
            doc.plainText = parseTxt(filePath);
            doc.htmlContent = "<pre style='font-family: inherit; font-size: 14px; white-space: pre-wrap;'>" + doc.plainText.toHtmlEscaped() + "</pre>";
            break;
    }

    return doc;
}
