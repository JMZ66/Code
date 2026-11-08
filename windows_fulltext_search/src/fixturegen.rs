//! Real containers, not renamed extensions. OOXML/ODF/RTF/HTML/PDF are written
//! as the formats they claim to be. Legacy binary Office files are not invented
//! here; those fixtures are produced separately when a converter is available.

use std::io::{Write, Cursor};
use std::path::Path;

use zip::write::SimpleFileOptions;
use zip::{CompressionMethod, ZipWriter};

pub fn write_corpus(root: &Path) -> std::io::Result<()> {
    std::fs::create_dir_all(root)?;
    std::fs::write(
        root.join("包装材料.txt"),
        "封面\n包装材料质量检测报告\n正文里还有单独的量检两个字。\n",
    )?;
    std::fs::write(
        root.join("大小写.txt"),
        "Quality is not quality. QUALITY stays distinct.\nStraße\n",
    )?;
    std::fs::write(root.join("onlylower.txt"), "quality only\n")?;
    std::fs::write(
        root.join("单词.txt"),
        "quality detection\nqualitydetection should stay one token\n",
    )?;
    std::fs::write(root.join("布尔甲.txt"), "苹果 香蕉\n")?;
    std::fs::write(root.join("布尔乙.txt"), "只有苹果\n")?;
    std::fs::write(root.join("标点.txt"), "质量，检测\n")?;
    std::fs::write(
        root.join("notes.md"),
        "# 标题\n\n包装材料质量检测报告的 Markdown 副本。\n",
    )?;
    std::fs::write(
        root.join("表.csv"),
        "名称,项目\n包装材料,质量检测报告\n",
    )?;
    std::fs::write(
        root.join("数据.json"),
        "{\"title\":\"包装材料质量检测报告\"}\n",
    )?;
    std::fs::write(
        root.join("数据.xml"),
        "<?xml version=\"1.0\" encoding=\"UTF-8\"?><root><item>包装材料质量检测报告</item></root>\n",
    )?;
    std::fs::write(
        root.join("页面.html"),
        "<!DOCTYPE html><html><head><meta charset=\"utf-8\"><script>var SECRETTOKEN=1;</script><style>.x{color:red}</style></head><body><p>包装材料质量检测报告</p></body></html>\n",
    )?;
    std::fs::write(root.join("说明.rtf"), rtf_unicode("包装材料质量检测报告"))?;
    write_zip(
        &root.join("正文.docx"),
        &[
            ("[Content_Types].xml", CONTENT_TYPES_DOCX),
            ("_rels/.rels", RELS_DOCX),
            ("word/_rels/document.xml.rels", DOC_RELS),
            ("word/document.xml", DOC_XML),
            ("word/header1.xml", HEADER_XML),
            ("word/footer1.xml", FOOTER_XML),
        ],
    )?;
    std::fs::copy(root.join("正文.docx"), root.join("宏文档.docm"))?;
    write_zip(
        &root.join("表.xlsx"),
        &[
            ("[Content_Types].xml", CONTENT_TYPES_XLSX),
            ("_rels/.rels", RELS_XLSX),
            ("xl/_rels/workbook.xml.rels", WB_RELS),
            ("xl/workbook.xml", WORKBOOK_XML),
            ("xl/sharedStrings.xml", SST_XML),
            ("xl/styles.xml", STYLES_XML),
            ("xl/worksheets/sheet1.xml", SHEET_XML),
            ("xl/worksheets/sheet2.xml", SHEET2_XML),
        ],
    )?;
    std::fs::copy(root.join("表.xlsx"), root.join("宏表.xlsm"))?;
    write_zip(
        &root.join("幻灯.pptx"),
        &[
            ("[Content_Types].xml", CONTENT_TYPES_PPTX),
            ("_rels/.rels", RELS_PPTX),
            ("ppt/_rels/presentation.xml.rels", PRES_RELS),
            ("ppt/presentation.xml", PRESENTATION_XML),
            ("ppt/slides/_rels/slide1.xml.rels", SLIDE_RELS),
            ("ppt/slides/slide1.xml", SLIDE1_XML),
            ("ppt/slides/slide2.xml", SLIDE2_XML),
            ("ppt/slides/_rels/slide2.xml.rels", SLIDE_RELS),
        ],
    )?;
    write_zip(
        &root.join("文字.odt"),
        &[
            ("mimetype", "application/vnd.oasis.opendocument.text"),
            ("content.xml", ODT_CONTENT),
            ("styles.xml", ODT_STYLES),
        ],
    )?;
    write_zip(
        &root.join("表.ods"),
        &[
            ("mimetype", "application/vnd.oasis.opendocument.spreadsheet"),
            ("content.xml", ODS_CONTENT),
        ],
    )?;
    write_zip(
        &root.join("幻灯.odp"),
        &[
            ("mimetype", "application/vnd.oasis.opendocument.presentation"),
            ("content.xml", ODP_CONTENT),
        ],
    )?;
    std::fs::write(root.join("分页.pdf"), simple_pdf(&[
        "HelloPageOneAlpha",
        "HelloPageTwoBeta",
        "",
    ]))?;
    Ok(())
}

pub fn rtf_unicode(text: &str) -> String {
    let mut body = String::from("{\\rtf1\\ansi\\uc1 ");
    for ch in text.chars() {
        body.push_str(&format!("\\u{}?", ch as u32));
    }
    body.push('}');
    body
}

fn write_zip(path: &Path, files: &[(&str, &str)]) -> std::io::Result<()> {
    let file = std::fs::File::create(path)?;
    let mut zip = ZipWriter::new(file);
    let opts = SimpleFileOptions::default().compression_method(CompressionMethod::Deflated);
    for (name, body) in files {
        zip.start_file(*name, opts)
            .map_err(|err| std::io::Error::other(err.to_string()))?;
        zip.write_all(body.as_bytes())?;
    }
    zip.finish()
        .map_err(|err| std::io::Error::other(err.to_string()))?;
    Ok(())
}

fn simple_pdf(pages: &[&str]) -> Vec<u8> {
    let mut objects: Vec<String> = Vec::new();
    objects.push("<< /Type /Catalog /Pages 2 0 R >>".into());
    let mut kids = String::new();
    let font_id = 3 + pages.len() * 2;
    for (i, _) in pages.iter().enumerate() {
        let page_id = 3 + i * 2;
        if !kids.is_empty() {
            kids.push(' ');
        }
        kids.push_str(&format!("{page_id} 0 R"));
    }
    objects.push(format!(
        "<< /Type /Pages /Count {} /Kids [{}] >>",
        pages.len(),
        kids
    ));
    for (i, text) in pages.iter().enumerate() {
        let content_id = 4 + i * 2;
        let stream = if text.is_empty() {
            String::new()
        } else {
            format!("BT /F1 18 Tf 72 720 Td ({text}) Tj ET")
        };
        objects.push(format!(
            "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents {content_id} 0 R /Resources << /Font << /F1 {font_id} 0 R >> >> >>"
        ));
        objects.push(format!(
            "<< /Length {} >>\nstream\n{stream}\nendstream",
            stream.len()
        ));
    }
    objects.push("<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>".into());
    let mut out = String::from("%PDF-1.4\n");
    let mut offsets = vec![0usize];
    for (i, obj) in objects.iter().enumerate() {
        offsets.push(out.len());
        out.push_str(&format!("{} 0 obj\n{}\nendobj\n", i + 1, obj));
    }
    let xref = out.len();
    out.push_str(&format!("xref\n0 {}\n", objects.len() + 1));
    out.push_str("0000000000 65535 f \n");
    for off in offsets.iter().skip(1) {
        out.push_str(&format!("{off:010} 00000 n \n"));
    }
    out.push_str(&format!(
        "trailer << /Size {} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n",
        objects.len() + 1
    ));
    let _ = Cursor::new(&out);
    out.into_bytes()
}

const CONTENT_TYPES_DOCX: &str = r#"<?xml version="1.0" encoding="UTF-8"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Default Extension="xml" ContentType="application/xml"/>
  <Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>
  <Override PartName="/word/header1.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.header+xml"/>
  <Override PartName="/word/footer1.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.footer+xml"/>
</Types>"#;

const RELS_DOCX: &str = r#"<?xml version="1.0" encoding="UTF-8"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>
</Relationships>"#;

const DOC_RELS: &str = r#"<?xml version="1.0" encoding="UTF-8"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/header" Target="header1.xml"/>
  <Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/footer" Target="footer1.xml"/>
</Relationships>"#;

const DOC_XML: &str = r#"<?xml version="1.0" encoding="UTF-8"?>
<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">
  <w:body>
    <w:p><w:r><w:t>包装材料质量检测报告</w:t></w:r></w:p>
    <w:tbl>
      <w:tr>
        <w:tc><w:p><w:r><w:t>表格单元格甲</w:t></w:r></w:p></w:tc>
        <w:tc><w:p><w:r><w:t>表格单元格乙</w:t></w:r></w:p></w:tc>
      </w:tr>
    </w:tbl>
    <w:sectPr>
      <w:headerReference w:type="default" r:id="rId1"/>
      <w:footerReference w:type="default" r:id="rId2"/>
    </w:sectPr>
  </w:body>
</w:document>"#;

const HEADER_XML: &str = r#"<?xml version="1.0" encoding="UTF-8"?>
<w:hdr xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
  <w:p><w:r><w:t>页眉质量检测</w:t></w:r></w:p>
</w:hdr>"#;

const FOOTER_XML: &str = r#"<?xml version="1.0" encoding="UTF-8"?>
<w:ftr xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
  <w:p><w:r><w:t>页脚检测说明</w:t></w:r></w:p>
</w:ftr>"#;

const CONTENT_TYPES_XLSX: &str = r#"<?xml version="1.0" encoding="UTF-8"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Default Extension="xml" ContentType="application/xml"/>
  <Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>
  <Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>
  <Override PartName="/xl/worksheets/sheet2.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>
  <Override PartName="/xl/sharedStrings.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sharedStrings+xml"/>
  <Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>
</Types>"#;

const RELS_XLSX: &str = r#"<?xml version="1.0" encoding="UTF-8"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>
</Relationships>"#;

const WB_RELS: &str = r#"<?xml version="1.0" encoding="UTF-8"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>
  <Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet2.xml"/>
  <Relationship Id="rId3" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/sharedStrings" Target="sharedStrings.xml"/>
  <Relationship Id="rId4" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>
</Relationships>"#;

const WORKBOOK_XML: &str = r#"<?xml version="1.0" encoding="UTF-8"?>
<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">
  <sheets>
    <sheet name="材料表" sheetId="1" r:id="rId1"/>
    <sheet name="汇总" sheetId="2" r:id="rId2"/>
  </sheets>
</workbook>"#;

const SST_XML: &str = r#"<?xml version="1.0" encoding="UTF-8"?>
<sst xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" count="2" uniqueCount="2">
  <si><t>包装材料质量检测报告</t></si>
  <si><t>量检</t></si>
</sst>"#;

const STYLES_XML: &str = r#"<?xml version="1.0" encoding="UTF-8"?>
<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
  <fonts count="1"><font><sz val="11"/><name val="Calibri"/></font></fonts>
  <fills count="1"><fill><patternFill patternType="none"/></fill></fills>
  <borders count="1"><border/></borders>
  <cellStyleXfs count="1"><xf/></cellStyleXfs>
  <cellXfs count="1"><xf/></cellXfs>
</styleSheet>"#;

const SHEET_XML: &str = r#"<?xml version="1.0" encoding="UTF-8"?>
<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
  <sheetData>
    <row r="1"><c r="A1" t="s"><v>0</v></c></row>
    <row r="2"><c r="B2"><v>42</v></c></row>
    <row r="3"><c r="C3"><f>SUM(B2,1)</f><v>43</v></c></row>
    <row r="4"><c r="D4"><f>SUM(B2,99)</f></c></row>
  </sheetData>
</worksheet>"#;

const SHEET2_XML: &str = r#"<?xml version="1.0" encoding="UTF-8"?>
<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
  <sheetData>
    <row r="1"><c r="A1" t="s"><v>1</v></c></row>
  </sheetData>
</worksheet>"#;

const CONTENT_TYPES_PPTX: &str = r#"<?xml version="1.0" encoding="UTF-8"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Default Extension="xml" ContentType="application/xml"/>
  <Override PartName="/ppt/presentation.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.presentation.main+xml"/>
  <Override PartName="/ppt/slides/slide1.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.slide+xml"/>
  <Override PartName="/ppt/slides/slide2.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.slide+xml"/>
</Types>"#;

const RELS_PPTX: &str = r#"<?xml version="1.0" encoding="UTF-8"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="ppt/presentation.xml"/>
</Relationships>"#;

const PRES_RELS: &str = r#"<?xml version="1.0" encoding="UTF-8"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/slide" Target="slides/slide1.xml"/>
  <Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/slide" Target="slides/slide2.xml"/>
</Relationships>"#;

const PRESENTATION_XML: &str = r#"<?xml version="1.0" encoding="UTF-8"?>
<p:presentation xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">
  <p:sldIdLst>
    <p:sldId id="256" r:id="rId1"/>
    <p:sldId id="257" r:id="rId2"/>
  </p:sldIdLst>
</p:presentation>"#;

const SLIDE_RELS: &str = r#"<?xml version="1.0" encoding="UTF-8"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"/>"#;

const SLIDE1_XML: &str = r#"<?xml version="1.0" encoding="UTF-8"?>
<p:sld xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main" xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main">
  <p:cSld><p:spTree>
    <p:sp><p:txBody><a:p><a:r><a:t>幻灯片一包装材料质量检测报告</a:t></a:r></a:p></p:txBody></p:sp>
  </p:spTree></p:cSld>
</p:sld>"#;

const SLIDE2_XML: &str = r#"<?xml version="1.0" encoding="UTF-8"?>
<p:sld xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main" xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main">
  <p:cSld><p:spTree>
    <p:sp><p:txBody><a:p><a:r><a:t>第二页量检</a:t></a:r></a:p></p:txBody></p:sp>
  </p:spTree></p:cSld>
</p:sld>"#;

const ODT_CONTENT: &str = r#"<?xml version="1.0" encoding="UTF-8"?>
<office:document-content xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0" xmlns:text="urn:oasis:names:tc:opendocument:xmlns:text:1.0" xmlns:table="urn:oasis:names:tc:opendocument:xmlns:table:1.0">
  <office:body><office:text>
    <text:p>包装材料质量检测报告</text:p>
    <table:table table:name="表1"><table:table-row>
      <table:table-cell><text:p>表格单元格甲</text:p></table:table-cell>
    </table:table-row></table:table>
  </office:text></office:body>
</office:document-content>"#;

const ODT_STYLES: &str = r#"<?xml version="1.0" encoding="UTF-8"?>
<office:document-styles xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0" xmlns:style="urn:oasis:names:tc:opendocument:xmlns:style:1.0" xmlns:text="urn:oasis:names:tc:opendocument:xmlns:text:1.0">
  <office:master-styles><style:master-page style:name="Standard">
    <style:header><text:p>页眉质量检测</text:p></style:header>
    <style:footer><text:p>页脚检测说明</text:p></style:footer>
  </style:master-page></office:master-styles>
</office:document-styles>"#;

const ODS_CONTENT: &str = r#"<?xml version="1.0" encoding="UTF-8"?>
<office:document-content xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0" xmlns:text="urn:oasis:names:tc:opendocument:xmlns:text:1.0" xmlns:table="urn:oasis:names:tc:opendocument:xmlns:table:1.0">
  <office:body><office:spreadsheet>
    <table:table table:name="材料表">
      <table:table-row>
        <table:table-cell office:value-type="string"><text:p>包装材料质量检测报告</text:p></table:table-cell>
        <table:table-cell office:value-type="float" office:value="42"><text:p>42</text:p></table:table-cell>
        <table:table-cell office:value-type="float" office:value="43" table:formula="of:=SUM([.B1];1)"><text:p>43</text:p></table:table-cell>
        <table:table-cell table:formula="of:=SUM([.B1];99)"/>
      </table:table-row>
    </table:table>
  </office:spreadsheet></office:body>
</office:document-content>"#;

const ODP_CONTENT: &str = r#"<?xml version="1.0" encoding="UTF-8"?>
<office:document-content xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0" xmlns:draw="urn:oasis:names:tc:opendocument:xmlns:drawing:1.0" xmlns:text="urn:oasis:names:tc:opendocument:xmlns:text:1.0">
  <office:body><office:presentation>
    <draw:page draw:name="第一页"><text:p>幻灯片一包装材料质量检测报告</text:p></draw:page>
    <draw:page draw:name="第二页"><text:p>第二页量检</text:p></draw:page>
  </office:presentation></office:body>
</office:document-content>"#;
