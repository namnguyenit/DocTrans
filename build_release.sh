#!/bin/bash
set -e
cd /Users/nhannt/Desktop/desktop/project/readDoc

echo "Building readDoc project..."
mkdir -p build
cd build
cmake ..
make -j8
cd ..

echo "Running macdeployqt..."
/opt/homebrew/bin/macdeployqt build/readDoc.app || true

echo "Cleaning extended attributes..."
xattr -cr build/readDoc.app || true

echo "Signing binaries..."
codesign --force --sign - build/readDoc.app || true

echo "Creating DMG..."
cd build
rm -f readDoc_v1.dmg
hdiutil create -volname readDoc -srcfolder readDoc.app -ov -format UDZO readDoc_v1.dmg
echo "Done! readDoc_v1.dmg created in build/"
