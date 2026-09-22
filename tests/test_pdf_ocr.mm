#include <QCoreApplication>
#include <QTemporaryDir>
#include <QStringList>

#include "readDoc/Data/PdfExtractor.h"

#import <AppKit/AppKit.h>
#import <PDFKit/PDFKit.h>

int main(int argc, char *argv[]) {
    QCoreApplication application(argc, argv);
    QTemporaryDir temporary;
    if (!temporary.isValid()) return 1;
    const QString pdfPath = temporary.filePath("image-only.pdf");

    @autoreleasepool {
        NSImage *image = [[NSImage alloc] initWithSize:NSMakeSize(1200, 800)];
        [image lockFocus];
        [[NSColor whiteColor] setFill];
        NSRectFill(NSMakeRect(0, 0, 1200, 800));
        NSDictionary *attributes = @{
            NSFontAttributeName: [NSFont systemFontOfSize:52 weight:NSFontWeightSemibold],
            NSForegroundColorAttributeName: [NSColor blackColor]
        };
        [@"PRIVATE TECHNICAL DOCUMENT" drawAtPoint:NSMakePoint(100, 560)
                                      withAttributes:attributes];
        [@"Local OCR verification" drawAtPoint:NSMakePoint(100, 450)
                                 withAttributes:@{
            NSFontAttributeName: [NSFont systemFontOfSize:38],
            NSForegroundColorAttributeName: [NSColor blackColor]
        }];
        [image unlockFocus];

        PDFPage *page = [[PDFPage alloc] initWithImage:image];
        PDFDocument *document = [[PDFDocument alloc] init];
        [document insertPage:page atIndex:0];
        if (![document writeToURL:[NSURL fileURLWithPath:pdfPath.toNSString()]]) return 2;
    }

    const QStringList pages = PdfExtractor::extractPages(pdfPath);
    if (pages.size() != 1) return 3;
    const QString recognized = pages.first().toUpper();
    if (!recognized.contains("PRIVATE") || !recognized.contains("TECHNICAL")) return 4;
    return 0;
}
