/**
 * Browser-side 终审 Excel (.xlsx) generator — no Python / SheetJS required.
 * Produces a valid OOXML workbook (ZIP store) matching the server export columns.
 */
(function (global) {
  'use strict';

  var MECHANICS = [
    ['waterOutliers', '放水未集中'],
    ['p15AvoidableDeaths', '转阶段死亡'],
    ['passageCliffMistakes', '过场失误'],
    ['p1SilverArrowMissedFights', 'P1银锋射怪失误'],
    ['p1SilverArrowDeaths', 'P1银锋高伤致死'],
    ['missedShadows', 'P2拉弓未中幻影'],
    ['collapsingVoidSnapAiming', '崩裂甩狙'],
    ['gravityLineViolation', '重力坍缩致死违规'],
    ['voidGraspHealingLow', '空虚之握治疗不足'],
    ['tankRiftSlashFailure', '裂隙换坦失误'],
    ['voreluthVulnerabilityFade', 'P1龌勒易伤'],
  ];

  var HEADERS = ['ID', '职责', '判定次数']
    .concat(MECHANICS.map(function (m) { return m[1]; }))
    .concat(['申诉次数', '原因', '追加次数', '追加原因', '总计']);

  var CRC_TABLE = (function () {
    var table = new Uint32Array(256);
    for (var n = 0; n < 256; n++) {
      var c = n;
      for (var k = 0; k < 8; k++) c = (c & 1) ? (0xedb88320 ^ (c >>> 1)) : (c >>> 1);
      table[n] = c >>> 0;
    }
    return table;
  })();

  function crc32(bytes) {
    var c = 0xffffffff;
    for (var i = 0; i < bytes.length; i++) c = CRC_TABLE[(c ^ bytes[i]) & 0xff] ^ (c >>> 8);
    return (c ^ 0xffffffff) >>> 0;
  }

  function u16(n) {
    return new Uint8Array([n & 0xff, (n >>> 8) & 0xff]);
  }

  function u32(n) {
    return new Uint8Array([n & 0xff, (n >>> 8) & 0xff, (n >>> 16) & 0xff, (n >>> 24) & 0xff]);
  }

  function concat(chunks) {
    var total = 0;
    for (var i = 0; i < chunks.length; i++) total += chunks[i].length;
    var out = new Uint8Array(total);
    var off = 0;
    for (var j = 0; j < chunks.length; j++) {
      out.set(chunks[j], off);
      off += chunks[j].length;
    }
    return out;
  }

  function enc(str) {
    return new TextEncoder().encode(str);
  }

  function xmlEscape(value) {
    return String(value == null ? '' : value)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }

  function colLetter(index1) {
    var n = index1;
    var s = '';
    while (n > 0) {
      var m = (n - 1) % 26;
      s = String.fromCharCode(65 + m) + s;
      n = Math.floor((n - 1) / 26);
    }
    return s;
  }

  function cellRef(col1, row1) {
    return colLetter(col1) + String(row1);
  }

  function safeInt(value) {
    var n = Number(value);
    if (!isFinite(n)) return 0;
    return Math.trunc(n);
  }

  function zipStore(files) {
    var locals = [];
    var centrals = [];
    var offset = 0;
    for (var i = 0; i < files.length; i++) {
      var nameBytes = enc(files[i].name);
      var data = files[i].data;
      var crc = crc32(data);
      var local = concat([
        u32(0x04034b50),
        u16(20),
        u16(0),
        u16(0),
        u16(0),
        u16(0),
        u32(crc),
        u32(data.length),
        u32(data.length),
        u16(nameBytes.length),
        u16(0),
        nameBytes,
        data,
      ]);
      var central = concat([
        u32(0x02014b50),
        u16(20),
        u16(20),
        u16(0),
        u16(0),
        u16(0),
        u16(0),
        u32(crc),
        u32(data.length),
        u32(data.length),
        u16(nameBytes.length),
        u16(0),
        u16(0),
        u16(0),
        u16(0),
        u32(0),
        u32(offset),
        nameBytes,
      ]);
      locals.push(local);
      centrals.push(central);
      offset += local.length;
    }
    var centralDir = concat(centrals);
    var end = concat([
      u32(0x06054b50),
      u16(0),
      u16(0),
      u16(files.length),
      u16(files.length),
      u32(centralDir.length),
      u32(offset),
      u16(0),
    ]);
    return concat(locals.concat([centralDir, end]));
  }

  function stylesXml() {
    // Font child order matters for Excel/WPS: b → sz → color → name.
    // cellXfs must include xfId referencing cellStyleXfs.
    return '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>' +
      '<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">' +
      '<fonts count="4">' +
      '<font><sz val="11"/><color theme="1"/><name val="Microsoft YaHei"/><family val="2"/></font>' +
      '<font><b/><sz val="11"/><color rgb="FFF9FAFB"/><name val="Microsoft YaHei"/><family val="2"/></font>' +
      '<font><sz val="10"/><color rgb="FF111827"/><name val="Microsoft YaHei"/><family val="2"/></font>' +
      '<font><b/><sz val="10"/><color rgb="FF9D174D"/><name val="Microsoft YaHei"/><family val="2"/></font>' +
      '</fonts>' +
      '<fills count="5">' +
      '<fill><patternFill patternType="none"/></fill>' +
      '<fill><patternFill patternType="gray125"/></fill>' +
      '<fill><patternFill patternType="solid"><fgColor rgb="FF1F2937"/></patternFill></fill>' +
      '<fill><patternFill patternType="solid"><fgColor rgb="FFF3F4F6"/></patternFill></fill>' +
      '<fill><patternFill patternType="solid"><fgColor rgb="FFFCE7F3"/></patternFill></fill>' +
      '</fills>' +
      '<borders count="2">' +
      '<border/>' +
      '<border>' +
      '<left style="thin"><color rgb="FF000000"/></left>' +
      '<right style="thin"><color rgb="FF000000"/></right>' +
      '<top style="thin"><color rgb="FF000000"/></top>' +
      '<bottom style="thin"><color rgb="FF000000"/></bottom>' +
      '</border>' +
      '</borders>' +
      '<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>' +
      '<cellXfs count="5">' +
      '<xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/>' +
      '<xf numFmtId="0" fontId="1" fillId="2" borderId="1" xfId="0" applyFont="1" applyFill="1" applyBorder="1" applyAlignment="1"><alignment horizontal="center" vertical="center" wrapText="1"/></xf>' +
      '<xf numFmtId="0" fontId="2" fillId="3" borderId="1" xfId="0" applyFont="1" applyFill="1" applyBorder="1" applyAlignment="1"><alignment horizontal="left" vertical="center" wrapText="1"/></xf>' +
      '<xf numFmtId="0" fontId="2" fillId="3" borderId="1" xfId="0" applyFont="1" applyFill="1" applyBorder="1" applyAlignment="1"><alignment horizontal="center" vertical="center" wrapText="1"/></xf>' +
      '<xf numFmtId="0" fontId="3" fillId="4" borderId="1" xfId="0" applyFont="1" applyFill="1" applyBorder="1" applyAlignment="1"><alignment horizontal="center" vertical="center" wrapText="1"/></xf>' +
      '</cellXfs>' +
      '</styleSheet>';
  }

  function sheetXml(players, bossName, date, pointsPerCount) {
    var cols = HEADERS.length;
    var recognitionCol = 3;
    var appealCol = 3 + MECHANICS.length + 1;
    var additionalCol = appealCol + 2;
    var totalCol = cols;
    var rows = [];
    var headerCells = [];
    // style 1 = header (dark bar); 2 = left data; 3 = center data; 4 = total
    for (var c = 1; c <= cols; c++) {
      headerCells.push(
        '<c r="' + cellRef(c, 1) + '" t="inlineStr" s="1"><is><t>' + xmlEscape(HEADERS[c - 1]) + '</t></is></c>'
      );
    }
    rows.push('<row r="1" ht="30" customHeight="1">' + headerCells.join('') + '</row>');

    for (var i = 0; i < players.length; i++) {
      var p = players[i] || {};
      var breakdown = p.breakdown || {};
      var rowNum = i + 2;
      var recognition = safeInt(p.recognitionCount);
      var appeal = safeInt(p.appealAcquittalCount);
      var additional = safeInt(p.additionalCount);
      var values = [
        { text: String(p.name || ''), style: 2 },
        { text: String(p.rolesText || ''), style: 3 },
        { num: recognition, style: 3 },
      ];
      for (var m = 0; m < MECHANICS.length; m++) {
        values.push({ num: safeInt(breakdown[MECHANICS[m][0]]), style: 3 });
      }
      values.push({ num: appeal, style: 3 });
      values.push({ text: String(p.appealAcquittalReasons || '').trim(), style: 3, allowEmpty: true });
      values.push({ num: additional, style: 3 });
      values.push({ text: String(p.additionalReasons || '').trim(), style: 3, allowEmpty: true });

      var cells = [];
      for (var col = 1; col <= values.length; col++) {
        var item = values[col - 1];
        var ref = cellRef(col, rowNum);
        if (Object.prototype.hasOwnProperty.call(item, 'num')) {
          cells.push('<c r="' + ref + '" s="' + item.style + '"><v>' + item.num + '</v></c>');
        } else if (item.text) {
          cells.push('<c r="' + ref + '" t="inlineStr" s="' + item.style + '"><is><t>' + xmlEscape(item.text) + '</t></is></c>');
        } else if (item.allowEmpty) {
          cells.push('<c r="' + ref + '" s="' + item.style + '"/>');
        } else {
          cells.push('<c r="' + ref + '" t="inlineStr" s="' + item.style + '"><is><t></t></is></c>');
        }
      }
      var totalRef = cellRef(totalCol, rowNum);
      var formula = '(' + cellRef(recognitionCol, rowNum) + '-' + cellRef(appealCol, rowNum) + '+' + cellRef(additionalCol, rowNum) + ')*' + pointsPerCount;
      var totalVal = (recognition - appeal + additional) * pointsPerCount;
      cells.push('<c r="' + totalRef + '" s="4"><f>' + formula + '</f><v>' + totalVal + '</v></c>');
      rows.push('<row r="' + rowNum + '">' + cells.join('') + '</row>');
    }

    var lastRow = Math.max(1, players.length + 1);
    return '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>' +
      '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">' +
      '<dimension ref="A1:' + cellRef(cols, lastRow) + '"/>' +
      '<sheetViews><sheetView workbookViewId="0"><pane ySplit="1" topLeftCell="A2" activePane="bottomLeft" state="frozen"/></sheetView></sheetViews>' +
      '<sheetFormatPr defaultRowHeight="18"/>' +
      '<cols>' +
      '<col min="1" max="1" width="16" customWidth="1"/>' +
      '<col min="2" max="2" width="14" customWidth="1"/>' +
      '<col min="3" max="' + (2 + MECHANICS.length) + '" width="12" customWidth="1"/>' +
      '<col min="' + appealCol + '" max="' + appealCol + '" width="10" customWidth="1"/>' +
      '<col min="' + (appealCol + 1) + '" max="' + (appealCol + 1) + '" width="36" customWidth="1"/>' +
      '<col min="' + additionalCol + '" max="' + additionalCol + '" width="10" customWidth="1"/>' +
      '<col min="' + (additionalCol + 1) + '" max="' + (additionalCol + 1) + '" width="36" customWidth="1"/>' +
      '<col min="' + totalCol + '" max="' + totalCol + '" width="10" customWidth="1"/>' +
      '</cols>' +
      '<sheetData>' + rows.join('') + '</sheetData>' +
      '</worksheet>';
  }

  function buildXlsxBytes(payload, options) {
    options = options || {};
    var bossName = options.bossName || '宇宙之冕';
    var date = String((payload && payload.date) || new Date().toISOString().slice(0, 10));
    var players = (payload && payload.players) || [];
    var pointsPerCount = safeInt(payload && payload.pointsPerCount) || 10;
    var sheetName = (bossName + '_' + date.replace(/-/g, '')).slice(0, 31);

    var files = [
      {
        name: '[Content_Types].xml',
        data: enc(
          '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>' +
          '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">' +
          '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>' +
          '<Default Extension="xml" ContentType="application/xml"/>' +
          '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>' +
          '<Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>' +
          '<Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>' +
          '</Types>'
        ),
      },
      {
        name: '_rels/.rels',
        data: enc(
          '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>' +
          '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">' +
          '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>' +
          '</Relationships>'
        ),
      },
      {
        name: 'xl/workbook.xml',
        data: enc(
          '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>' +
          '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" ' +
          'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">' +
          '<sheets><sheet name="' + xmlEscape(sheetName) + '" sheetId="1" r:id="rId1"/></sheets>' +
          '</workbook>'
        ),
      },
      {
        name: 'xl/_rels/workbook.xml.rels',
        data: enc(
          '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>' +
          '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">' +
          '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>' +
          '<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>' +
          '</Relationships>'
        ),
      },
      { name: 'xl/styles.xml', data: enc(stylesXml()) },
      { name: 'xl/worksheets/sheet1.xml', data: enc(sheetXml(players, bossName, date, pointsPerCount)) },
    ];
    return zipStore(files);
  }

  function downloadVerdictXlsx(payload, options) {
    options = options || {};
    var bossName = options.bossName || '宇宙之冕';
    var date = String((payload && payload.date) || new Date().toISOString().slice(0, 10));
    var bytes = buildXlsxBytes(payload, options);
    var blob = new Blob([bytes], {
      type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    });
    var filename = options.filename || ('智力表_' + bossName + '_' + date + '.xlsx');
    var url = URL.createObjectURL(blob);
    var anchor = document.createElement('a');
    anchor.href = url;
    anchor.download = filename;
    anchor.click();
    setTimeout(function () { URL.revokeObjectURL(url); }, 1000);
    return { filename: filename, byteLength: bytes.length };
  }

  global.VerdictXlsx = {
    MECHANICS: MECHANICS,
    HEADERS: HEADERS,
    buildXlsxBytes: buildXlsxBytes,
    downloadVerdictXlsx: downloadVerdictXlsx,
  };
})(typeof window !== 'undefined' ? window : globalThis);
