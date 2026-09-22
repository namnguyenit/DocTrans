$ErrorActionPreference = "Stop"

Write-Host "Configuring MSYS2 / MinGW environment..."
# Đường dẫn mặc định của MSYS2. Bạn có thể thay đổi nếu bạn cài ở ổ khác (vd: D:\msys64)
$msysRoot = "C:\msys64"

if (Test-Path $msysRoot) {
    # Ưu tiên tìm các môi trường theo thứ tự: UCRT64 -> CLANG64 -> MINGW64
    if (Test-Path "$msysRoot\ucrt64\bin\cmake.exe") {
        $env:PATH = "$msysRoot\ucrt64\bin;$msysRoot\usr\bin;$env:PATH"
        Write-Host "Sử dụng môi trường MSYS2 UCRT64."
    } elseif (Test-Path "$msysRoot\clang64\bin\cmake.exe") {
        $env:PATH = "$msysRoot\clang64\bin;$msysRoot\usr\bin;$env:PATH"
        Write-Host "Sử dụng môi trường MSYS2 CLANG64."
    } elseif (Test-Path "$msysRoot\mingw64\bin\cmake.exe") {
        $env:PATH = "$msysRoot\mingw64\bin;$msysRoot\usr\bin;$env:PATH"
        Write-Host "Sử dụng môi trường MSYS2 MINGW64."
    } else {
        Write-Host "Đã tìm thấy MSYS2 nhưng không tìm thấy cmake. Vui lòng cài đặt cmake trong msys2."
    }
} else {
    Write-Warning "Không tìm thấy thư mục C:\msys64. Nếu MSYS2 của bạn nằm ở ổ đĩa khác, vui lòng sửa lại biến `$msysRoot trong script này."
}

Write-Host "Building readDoc project for Windows..."
if (-not (Test-Path "build")) {
    New-Item -ItemType Directory -Force -Path "build" | Out-Null
}

Set-Location build
# Với MSYS2, CMake thường dùng Ninja làm Generator mặc định (nhanh hơn MinGW Makefiles)
cmake .. -G "Ninja" -DCMAKE_BUILD_TYPE=Release

if ($LASTEXITCODE -ne 0) {
    Write-Host "Ninja generator không thành công, thử dùng MinGW Makefiles..."
    cmake .. -G "MinGW Makefiles" -DCMAKE_BUILD_TYPE=Release
}

cmake --build . --config Release
Set-Location ..

Stop-Process -Name "readDoc" -Force -ErrorAction SilentlyContinue
Write-Host "Installing to local prefix to bundle..."
cmake --install build --config Release --prefix build/install_dir

Write-Host "Running windeployqt..."
# Run windeployqt to copy required Qt libraries (Core, Gui, Widgets, Pdf, PdfWidgets are automatically detected)
windeployqt --release --pdf build/install_dir/bin/readDoc.exe

Write-Host "Deploying compiler & third-party runtime DLLs (libfreetype, libstdc++, libgcc, libicu...)..."
$binDir = "$PWD\build\install_dir\bin"
$msysBin = "$msysRoot\ucrt64\bin"
if (-not (Test-Path $msysBin)) { $msysBin = "$msysRoot\clang64\bin" }
if (-not (Test-Path $msysBin)) { $msysBin = "$msysRoot\mingw64\bin" }

if (Test-Path $msysBin) {
    $allFiles = Get-ChildItem -Path $binDir -Recurse -Include "*.dll","*.exe"
    $needed = @{}
    $objdump = (Get-Command objdump.exe -ErrorAction SilentlyContinue).Source
    if (-not $objdump -and (Test-Path "$msysBin\objdump.exe")) { $objdump = "$msysBin\objdump.exe" }
    
    if ($objdump) {
        foreach ($file in $allFiles) {
            $dlls = (& $objdump -p $file.FullName | Select-String "DLL Name:\s*(.*\.dll)" | ForEach-Object { $_.Matches.Groups[1].Value })
            foreach ($d in $dlls) { $needed[$d] = $true }
        }
        $toCheck = [System.Collections.Generic.Queue[string]]::new()
        foreach ($d in $needed.Keys) { $toCheck.Enqueue($d) }
        while ($toCheck.Count -gt 0) {
            $d = $toCheck.Dequeue()
            $src = "$msysBin\$d"
            if (Test-Path $src) {
                $dst = "$binDir\$d"
                if (-not (Test-Path $dst)) {
                    Copy-Item $src $dst -Force
                    $subDlls = (& $objdump -p $src | Select-String "DLL Name:\s*(.*\.dll)" | ForEach-Object { $_.Matches.Groups[1].Value })
                    foreach ($sub in $subDlls) {
                        if (-not $needed.ContainsKey($sub)) {
                            $needed[$sub] = $true
                            $toCheck.Enqueue($sub)
                        }
                    }
                }
            }
        }
    }
}

Write-Host "Creating ZIP archive..."
if (Test-Path "build/readDoc_v1_windows.zip") {
    Remove-Item "build/readDoc_v1_windows.zip" -Force
}
Compress-Archive -Path build/install_dir/bin/* -DestinationPath build/readDoc_v1_windows.zip -Force

Write-Host "Done! readDoc_v1_windows.zip created in build/"
