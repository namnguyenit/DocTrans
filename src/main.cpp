#include <QApplication>
#include <QFileInfo>
#include <QTimer>
#include "readDoc/MainWindow.h"

int main(int argc, char *argv[]) {
    QApplication app(argc, argv);
    app.setApplicationName("readDoc");
    app.setOrganizationName("LifeOS");

    MainWindow window;
    window.show();

    const QStringList arguments = QCoreApplication::arguments();
    const bool bilingual = arguments.contains("--bilingual");
    int initialPage = 1;
    const int pageOption = arguments.indexOf("--page");
    if (pageOption >= 0 && pageOption + 1 < arguments.size()) {
        initialPage = qMax(1, arguments[pageOption + 1].toInt());
    }
    QString documentPath;
    for (int index = 1; index < arguments.size(); ++index) {
        if (arguments[index] == "--bilingual") continue;
        if (arguments[index] == "--page") {
            ++index;
            continue;
        }
        if (QFileInfo::exists(arguments[index])) {
            documentPath = QFileInfo(arguments[index]).absoluteFilePath();
            break;
        }
    }
    if (!documentPath.isEmpty()) {
        QTimer::singleShot(0, &window, [&window, documentPath, bilingual, initialPage]() {
            window.openDocument(documentPath, bilingual, initialPage);
        });
    }
    return app.exec();
}
