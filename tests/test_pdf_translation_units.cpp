#include "readDoc/UI/SplitViewReader.h"
#include <QApplication>
#include <QPdfWriter>
#include <QPainter>
#include <QTemporaryDir>
#include <QTimer>
#include <algorithm>

static void check(bool ok, const char *message) { if (!ok) qFatal("%s", message); }

int main(int argc, char **argv) {
    QApplication app(argc, argv);
    QTemporaryDir temporary;
    qputenv("READDOC_CACHE_DB", (temporary.path() + "/cache.sqlite3").toUtf8());
    const QString path = temporary.path() + "/source.pdf";
    { QPdfWriter writer(path); QPainter painter(&writer); painter.drawText(100, 100, "Source"); }
    DocumentContent document;
    document.type = DocumentType::PDF;
    document.filePath = path;
    PageLayoutData page;
    QStringList sentences;
    for (int i = 0; i < 16; ++i)
        sentences.append(QString("Sentence %1 checks the buffer before starting the transfer.").arg(i));
    const QString paragraph = sentences.join(' ');
    const QStringList immutable = {"123456789", "0x1F00 / 0XABCD", "[31:0]", "123.45 - 678.90", "DMA_CTRL_REG 0x01", "---", "QCS6490", "I2C", "LPDDR4X"};
    const QStringList prose = {"FACE", "bad", "64 bits", "Use separate queues to avoid blocking unrelated requests."};
    QStringList texts{paragraph}; texts.append(immutable); texts.append(prose);
    for (int i = 0; i < texts.size(); ++i) {
        LayoutBlock block;
        block.text = texts[i]; block.bbox = QRectF(40, 40 + i * 35, 500, 30);
        page.blocks.append(block);
    }
    page.text = texts.join("\n\n");
    document.pageLayouts.append(page);
    OfflineTranslator translator;
    SplitViewReader reader(&translator);
    QStringList submitted;
    int total = 0, done = 0, failures = 0;
    QObject::connect(&translator, &OfflineTranslator::translationPolishedReady, &app,
        [&](int, const QString &text) {
            check(text.startsWith("VI_RESULT: "), "test peer must return source payload");
            submitted.append(text.mid(QString("VI_RESULT: ").size()));
        });
    QObject::connect(&reader, &SplitViewReader::progressChanged, &app,
        [&](int, int finalDone, int count, bool, int failed) { done = finalDone; total = count; failures = failed; });
    reader.loadDocument(document);
    QTimer poll;
    QObject::connect(&poll, &QTimer::timeout, &app, [&] {
        if (!reader.isTranslationComplete()) return;
        check(failures == 0, "all PDF fragments finish");
        check(done == total && total > texts.size(), "long PDF paragraph must be split");
        check(total - submitted.size() == immutable.size(), "numeric and identifier cells bypass both models");
        for (const auto &text : submitted) check(text.size() <= 300, "every model input is bounded");
        for (const auto &text : prose) check(submitted.contains(text), "natural prose must still translate");
        QStringList fragments;
        for (const auto &text : submitted) if (!prose.contains(text)) fragments.append(text);
        std::sort(fragments.begin(), fragments.end(), [&](const QString &a, const QString &b) {
            return paragraph.indexOf(a) < paragraph.indexOf(b);
        });
        check(fragments.join(' ') == paragraph, "splitting loses or duplicates no source text");
        QString error;
        check(reader.exportToPdf(temporary.path() + "/translated.pdf", &error), qPrintable(error));
        app.exit(0);
    });
    poll.start(25);
    QTimer::singleShot(15000, &app, [&] { qFatal("PDF fragment test timed out"); });
    return app.exec();
}
