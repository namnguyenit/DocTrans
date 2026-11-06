cmake_minimum_required(VERSION 3.16)
project(readDoc VERSION 1.0.0 LANGUAGES CXX)

if(APPLE)
    enable_language(OBJCXX)
endif()

include(CTest)

set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

set(CMAKE_AUTOMOC ON)
set(CMAKE_AUTORCC ON)
set(CMAKE_AUTOUIC ON)

find_package(Qt6 REQUIRED COMPONENTS Core Gui Widgets Pdf PdfWidgets Concurrent)

include_directories(
    ${CMAKE_CURRENT_SOURCE_DIR}/include
)

if(APPLE)
    set(PDF_EXTRACTOR_SOURCE src/Data/PdfExtractor.mm)
elseif(UNIX OR WIN32)
    set(PDF_EXTRACTOR_SOURCE src/Data/PdfExtractorLinux.cpp)
else()
    message(FATAL_ERROR "readDoc currently supports macOS, Linux and Windows")
endif()

set(PROJECT_SOURCES
    src/main.cpp
    src/MainWindow.cpp
    include/readDoc/MainWindow.h
    src/System/OfflineTranslator.cpp
    include/readDoc/System/OfflineTranslator.h
    src/Data/DocumentParser.cpp
    include/readDoc/Data/DocumentParser.h
    ${PDF_EXTRACTOR_SOURCE}
    include/readDoc/Data/PdfExtractor.h
    src/UI/ReaderWidget.cpp
    include/readDoc/UI/ReaderWidget.h
    src/UI/SplitViewReader.cpp
    include/readDoc/UI/SplitViewReader.h
)

add_executable(readDoc ${PROJECT_SOURCES})

target_link_libraries(readDoc PRIVATE
    Qt6::Core
    Qt6::Gui
    Qt6::Widgets
    Qt6::Pdf
    Qt6::PdfWidgets
    Qt6::Concurrent
)

if(APPLE)
    target_link_libraries(readDoc PRIVATE
        "-framework Foundation"
        "-framework AppKit"
        "-framework PDFKit"
        "-framework Vision"
    )
    set_target_properties(readDoc PROPERTIES
        MACOSX_BUNDLE TRUE
        MACOSX_BUNDLE_BUNDLE_NAME "readDoc"
        MACOSX_BUNDLE_GUI_IDENTIFIER "com.nhannt.readdoc"
    )
    set(READDOC_RESOURCE_DESTINATION
        "$<TARGET_BUNDLE_DIR:readDoc>/Contents/Resources")
elseif(WIN32)
    target_compile_definitions(readDoc PRIVATE READDOC_WINDOWS=1)
    set(READDOC_RESOURCE_DESTINATION
        "$<TARGET_FILE_DIR:readDoc>/resources")
else()
    target_compile_definitions(readDoc PRIVATE READDOC_LINUX=1)
    set(READDOC_RESOURCE_DESTINATION
        "$<TARGET_FILE_DIR:readDoc>/resources")
endif()

set(READDOC_RESOURCE_FILES
    "${CMAKE_CURRENT_SOURCE_DIR}/src/Data/extract_pdf.py"
    "${CMAKE_CURRENT_SOURCE_DIR}/src/System/local_nmt_daemon.py"
    "${CMAKE_CURRENT_SOURCE_DIR}/src/System/local_cuda_server.py"
    "${CMAKE_CURRENT_SOURCE_DIR}/src/System/technical_glossary.json"
)

add_custom_target(sync_app_resources ALL
    COMMAND ${CMAKE_COMMAND} -E make_directory
            "${READDOC_RESOURCE_DESTINATION}"
    COMMAND ${CMAKE_COMMAND} -E copy_if_different
            "${CMAKE_CURRENT_SOURCE_DIR}/src/Data/extract_pdf.py"
            "${READDOC_RESOURCE_DESTINATION}/extract_pdf.py"
    COMMAND ${CMAKE_COMMAND} -E copy_if_different
            "${CMAKE_CURRENT_SOURCE_DIR}/src/System/local_nmt_daemon.py"
            "${READDOC_RESOURCE_DESTINATION}/local_nmt_daemon.py"
    COMMAND ${CMAKE_COMMAND} -E copy_if_different
            "${CMAKE_CURRENT_SOURCE_DIR}/src/System/local_cuda_server.py"
            "${READDOC_RESOURCE_DESTINATION}/local_cuda_server.py"
    COMMAND ${CMAKE_COMMAND} -E copy_if_different
            "${CMAKE_CURRENT_SOURCE_DIR}/src/System/technical_glossary.json"
            "${READDOC_RESOURCE_DESTINATION}/technical_glossary.json"
    DEPENDS
            readDoc
            ${READDOC_RESOURCE_FILES}
    COMMENT "Synchronizing bundled offline resources"
)

if(UNIX AND NOT APPLE)
    include(GNUInstallDirs)
    install(TARGETS readDoc RUNTIME DESTINATION ${CMAKE_INSTALL_BINDIR})
    install(FILES ${READDOC_RESOURCE_FILES}
            DESTINATION ${CMAKE_INSTALL_DATADIR}/readDoc)
elseif(WIN32)
    install(TARGETS readDoc RUNTIME DESTINATION bin)
    install(FILES ${READDOC_RESOURCE_FILES}
            DESTINATION bin/resources)
endif()

find_package(Python3 COMPONENTS Interpreter)
if(BUILD_TESTING AND Python3_Interpreter_FOUND)
    add_test(
        NAME pdf_layout
        COMMAND ${Python3_EXECUTABLE} ${CMAKE_CURRENT_SOURCE_DIR}/tests/test_pdf_layout.py
    )
    set_tests_properties(pdf_layout PROPERTIES
        ENVIRONMENT "PYTHONDONTWRITEBYTECODE=1"
    )
    add_test(
        NAME polish_pipeline
        COMMAND ${Python3_EXECUTABLE} ${CMAKE_CURRENT_SOURCE_DIR}/tests/test_polish_pipeline.py
    )
    add_test(NAME cuda_server COMMAND ${Python3_EXECUTABLE} ${CMAKE_CURRENT_SOURCE_DIR}/tests/test_cuda_server.py)
    add_test(NAME dense_pdf_patterns COMMAND ${Python3_EXECUTABLE} ${CMAKE_CURRENT_SOURCE_DIR}/tests/test_dense_pdf_patterns.py)
    set_tests_properties(polish_pipeline PROPERTIES
        ENVIRONMENT "PYTHONDONTWRITEBYTECODE=1"
    )
endif()

if(BUILD_TESTING)
    add_executable(test_translation_scheduler tests/test_translation_scheduler.cpp)
    target_link_libraries(test_translation_scheduler PRIVATE Qt6::Core)
    add_test(NAME translation_scheduler COMMAND test_translation_scheduler)
    if(Python3_Interpreter_FOUND)
        set(READDOC_TEST_SOURCES ${PROJECT_SOURCES})
        list(REMOVE_ITEM READDOC_TEST_SOURCES src/main.cpp)
        add_executable(test_multi_document tests/test_multi_document.cpp ${READDOC_TEST_SOURCES})
        get_target_property(READDOC_TEST_LIBRARIES readDoc LINK_LIBRARIES)
        target_link_libraries(test_multi_document PRIVATE ${READDOC_TEST_LIBRARIES})
        add_executable(test_large_pdf tests/test_large_pdf.cpp ${READDOC_TEST_SOURCES})
        set_target_properties(test_large_pdf PROPERTIES OUTPUT_NAME large_pdf_stress)
        target_link_libraries(test_large_pdf PRIVATE ${READDOC_TEST_LIBRARIES})
        add_executable(test_pdf_translation_units tests/test_pdf_translation_units.cpp ${READDOC_TEST_SOURCES})
        target_link_libraries(test_pdf_translation_units PRIVATE ${READDOC_TEST_LIBRARIES})
        if(WIN32)
            target_compile_definitions(test_multi_document PRIVATE READDOC_WINDOWS=1)
            target_compile_definitions(test_large_pdf PRIVATE READDOC_WINDOWS=1)
            target_compile_definitions(test_pdf_translation_units PRIVATE READDOC_WINDOWS=1)
        elseif(UNIX AND NOT APPLE)
            target_compile_definitions(test_multi_document PRIVATE READDOC_LINUX=1)
            target_compile_definitions(test_large_pdf PRIVATE READDOC_LINUX=1)
            target_compile_definitions(test_pdf_translation_units PRIVATE READDOC_LINUX=1)
        endif()
        file(MAKE_DIRECTORY "${CMAKE_CURRENT_BINARY_DIR}/test_resources")
        configure_file(tests/fixtures/local_nmt_daemon.py test_resources/local_nmt_daemon.py COPYONLY)
        configure_file(src/Data/extract_pdf.py test_resources/extract_pdf.py COPYONLY)
        add_test(NAME multi_document COMMAND test_multi_document)
        add_test(NAME pdf_translation_units COMMAND test_pdf_translation_units)
        add_executable(test_translator_shutdown tests/test_translator_shutdown.cpp
            src/System/OfflineTranslator.cpp include/readDoc/System/OfflineTranslator.h)
        target_link_libraries(test_translator_shutdown PRIVATE Qt6::Core)
        add_test(NAME translator_shutdown COMMAND test_translator_shutdown)
        add_executable(test_translation_literals tests/test_translation_literals.cpp
            src/System/OfflineTranslator.cpp include/readDoc/System/OfflineTranslator.h)
        target_link_libraries(test_translation_literals PRIVATE Qt6::Core)
        add_test(NAME translation_literals COMMAND test_translation_literals)
        set_tests_properties(translation_literals PROPERTIES TIMEOUT 15 ENVIRONMENT
            "READDOC_RESOURCE_DIR=${CMAKE_CURRENT_BINARY_DIR}/test_resources;READDOC_PYTHON=${Python3_EXECUTABLE}")
        set_tests_properties(translator_shutdown PROPERTIES TIMEOUT 15 ENVIRONMENT
            "READDOC_RESOURCE_DIR=${CMAKE_CURRENT_BINARY_DIR}/test_resources;READDOC_PYTHON=${Python3_EXECUTABLE}")
        set_tests_properties(pdf_translation_units PROPERTIES TIMEOUT 30 ENVIRONMENT
            "QT_QPA_PLATFORM=offscreen;READDOC_RESOURCE_DIR=${CMAKE_CURRENT_BINARY_DIR}/test_resources;READDOC_PYTHON=${Python3_EXECUTABLE}")
        set_tests_properties(multi_document PROPERTIES TIMEOUT 45 ENVIRONMENT
            "QT_QPA_PLATFORM=offscreen;READDOC_RESOURCE_DIR=${CMAKE_CURRENT_BINARY_DIR}/test_resources;READDOC_PYTHON=${Python3_EXECUTABLE};READDOC_TEST_SCREENSHOT=${CMAKE_CURRENT_BINARY_DIR}/multi_document.png")
    endif()
endif()

if(BUILD_TESTING AND APPLE)
    add_executable(test_pdf_ocr
        tests/test_pdf_ocr.mm
        src/Data/PdfExtractor.mm
        include/readDoc/Data/PdfExtractor.h
    )
    target_link_libraries(test_pdf_ocr PRIVATE
        Qt6::Core
        Qt6::Gui
        "-framework Foundation"
        "-framework AppKit"
        "-framework PDFKit"
        "-framework Vision"
    )
    add_test(NAME pdf_ocr COMMAND test_pdf_ocr)
    set_tests_properties(pdf_ocr PROPERTIES
        WORKING_DIRECTORY "${CMAKE_CURRENT_SOURCE_DIR}"
    )
endif()
