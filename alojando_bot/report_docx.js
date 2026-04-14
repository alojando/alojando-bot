/**
 * Generador de informe Word (.docx) para Alojando BOT.
 * Uso: node report_docx.js <input_json_path> <output_docx_path>
 *
 * Recibe un JSON con los datos del ComparisonResult y genera un .docx profesional.
 */
const fs = require("fs");
const {
    Document, Packer, Paragraph, TextRun, Table, TableRow, TableCell,
    Header, Footer, AlignmentType, LevelFormat, HeadingLevel,
    BorderStyle, WidthType, ShadingType, PageNumber, PageBreak
} = require("docx");

// Leer argumentos
const inputPath = process.argv[2];
const outputPath = process.argv[3];

if (!inputPath || !outputPath) {
    console.error("Uso: node report_docx.js <input.json> <output.docx>");
    process.exit(1);
}

const data = JSON.parse(fs.readFileSync(inputPath, "utf-8"));

// Colores
const PRIMARY = "2563EB";
const PRIMARY_DARK = "1E40AF";
const SUCCESS = "16A34A";
const WARNING = "D97706";
const DANGER = "DC2626";
const LIGHT_BG = "F0F4FF";
const LIGHT_BORDER = "CBD5E1";

// Helpers
const border = { style: BorderStyle.SINGLE, size: 1, color: LIGHT_BORDER };
const borders = { top: border, bottom: border, left: border, right: border };
const cellMargins = { top: 80, bottom: 80, left: 120, right: 120 };

function heading(text, level = HeadingLevel.HEADING_1) {
    return new Paragraph({ heading: level, children: [new TextRun(text)] });
}

function para(text, opts = {}) {
    return new Paragraph({
        spacing: { after: 120 },
        ...opts,
        children: [new TextRun({ font: "Arial", size: 22, ...opts.run, text })]
    });
}

function boldPara(label, value) {
    return new Paragraph({
        spacing: { after: 80 },
        children: [
            new TextRun({ font: "Arial", size: 22, bold: true, text: label }),
            new TextRun({ font: "Arial", size: 22, text: value })
        ]
    });
}

function bulletItem(text, reference = "bullets") {
    return new Paragraph({
        numbering: { reference, level: 0 },
        spacing: { after: 60 },
        children: [new TextRun({ font: "Arial", size: 22, text })]
    });
}

function sectionDivider() {
    return new Paragraph({
        spacing: { before: 200, after: 200 },
        border: { bottom: { style: BorderStyle.SINGLE, size: 6, color: PRIMARY, space: 1 } },
        children: []
    });
}

// Build document
const original = data.original || {};
const comparables = data.comparables || [];
const currency = original.currency || "USD";

const children = [];

// Title page
children.push(new Paragraph({ spacing: { before: 3000 } }));
children.push(new Paragraph({
    alignment: AlignmentType.CENTER,
    spacing: { after: 200 },
    children: [new TextRun({ font: "Arial", size: 56, bold: true, color: PRIMARY_DARK, text: "ALOJANDO BOT" })]
}));
children.push(new Paragraph({
    alignment: AlignmentType.CENTER,
    spacing: { after: 100 },
    children: [new TextRun({ font: "Arial", size: 32, color: "64748B", text: "Informe Comparativo de Mercado" })]
}));
children.push(new Paragraph({
    alignment: AlignmentType.CENTER,
    spacing: { after: 400 },
    children: [new TextRun({ font: "Arial", size: 24, color: "64748B", text: original.title || "Tu propiedad" })]
}));
children.push(new Paragraph({
    alignment: AlignmentType.CENTER,
    children: [new TextRun({
        font: "Arial", size: 22, color: "94A3B8",
        text: `Generado el ${new Date().toLocaleDateString("es-AR")} | ${comparables.length} comparables analizados`
    })]
}));

children.push(new Paragraph({ children: [new PageBreak()] }));

// Resumen ejecutivo
children.push(heading("Resumen Ejecutivo"));
children.push(sectionDivider());

children.push(boldPara("Propiedad: ", original.title || "No especificado"));
children.push(boldPara("Ubicacion: ", [original.address, original.city, original.country].filter(Boolean).join(", ") || "No especificada"));
children.push(boldPara("Tu precio: ", `${currency} ${(original.price_per_night || 0).toFixed(0)}/noche`));
children.push(boldPara("Comparables encontrados: ", `${comparables.length}`));
children.push(boldPara("Precio mediana del mercado: ", `${currency} ${(data.median_price || 0).toFixed(0)}/noche`));
children.push(boldPara("Rating promedio zona: ", `${(data.avg_rating || 0).toFixed(1)}/5.0`));

if (data.suggested_price_low > 0 && data.suggested_price_high > 0) {
    children.push(new Paragraph({ spacing: { before: 200 } }));
    children.push(new Paragraph({
        spacing: { after: 120 },
        shading: { fill: "DBEAFE", type: ShadingType.CLEAR },
        children: [new TextRun({
            font: "Arial", size: 24, bold: true, color: PRIMARY_DARK,
            text: `  Rango de precio sugerido: ${currency} ${data.suggested_price_low.toFixed(0)} - ${currency} ${data.suggested_price_high.toFixed(0)}/noche`
        })]
    }));
}

children.push(new Paragraph({ children: [new PageBreak()] }));

// Análisis de precios
children.push(heading("Analisis de Precios"));
children.push(sectionDivider());

if (data.pricing_suggestions && data.pricing_suggestions.length > 0) {
    data.pricing_suggestions.forEach(s => {
        children.push(bulletItem(s));
    });
}

// Tabla de estadísticas de precios
children.push(new Paragraph({ spacing: { before: 200 } }));
children.push(heading("Estadisticas de Precios", HeadingLevel.HEADING_2));

const priceStatsRows = [
    ["Metrica", "Valor"],
    ["Tu precio", `${currency} ${(original.price_per_night || 0).toFixed(0)}`],
    ["Precio promedio mercado", `${currency} ${(data.avg_price || 0).toFixed(0)}`],
    ["Precio mediana mercado", `${currency} ${(data.median_price || 0).toFixed(0)}`],
    ["Precio minimo", `${currency} ${(data.min_price || 0).toFixed(0)}`],
    ["Precio maximo", `${currency} ${(data.max_price || 0).toFixed(0)}`],
    ["Tu percentil", `${(data.price_percentile || 0).toFixed(0)}%`],
];

children.push(createTable(priceStatsRows, [4680, 4680]));

children.push(new Paragraph({ children: [new PageBreak()] }));

// Tabla de comparables
children.push(heading("Detalle de Comparables"));
children.push(sectionDivider());

const compHeaders = ["Portal", "Titulo", "Precio", "Rating", "Dormitorios"];
const compRows = [compHeaders];

// Agregar el original
compRows.push([
    (original.source || "manual").toUpperCase(),
    (original.title || "Tu propiedad").substring(0, 40),
    `${currency} ${(original.price_per_night || 0).toFixed(0)}`,
    `${(original.rating || 0).toFixed(1)}`,
    `${original.bedrooms || "-"}`
]);

comparables.slice(0, 20).forEach(c => {
    compRows.push([
        (c.source || "").toUpperCase(),
        (c.title || "").substring(0, 40),
        c.price_per_night > 0 ? `${currency} ${c.price_per_night.toFixed(0)}` : "-",
        c.rating > 0 ? c.rating.toFixed(1) : "-",
        c.bedrooms > 0 ? `${c.bedrooms}` : "-"
    ]);
});

const colWidths = [1400, 3800, 1500, 1200, 1460];
children.push(createTable(compRows, colWidths));

children.push(new Paragraph({ children: [new PageBreak()] }));

// Amenidades
children.push(heading("Analisis de Amenidades"));
children.push(sectionDivider());

if (data.common_amenities && data.common_amenities.length > 0) {
    children.push(heading("Amenidades mas comunes en la zona", HeadingLevel.HEADING_2));
    data.common_amenities.forEach(([amenity, count]) => {
        children.push(bulletItem(`${amenity} (${count} propiedades)`));
    });
}

if (data.missing_amenities && data.missing_amenities.length > 0) {
    children.push(heading("Amenidades que te faltan", HeadingLevel.HEADING_2));
    data.missing_amenities.forEach(a => {
        children.push(bulletItem(a));
    });
}

if (data.unique_amenities && data.unique_amenities.length > 0) {
    children.push(heading("Tus amenidades unicas (ventaja competitiva)", HeadingLevel.HEADING_2));
    data.unique_amenities.forEach(a => {
        children.push(bulletItem(a));
    });
}

if (data.amenity_suggestions) {
    children.push(new Paragraph({ spacing: { before: 200 } }));
    data.amenity_suggestions.forEach(s => children.push(bulletItem(s)));
}

children.push(new Paragraph({ children: [new PageBreak()] }));

// Calificaciones
children.push(heading("Calificaciones y Resenas"));
children.push(sectionDivider());
if (data.rating_comparison) {
    children.push(para(data.rating_comparison));
}

// Sugerencias de título
children.push(new Paragraph({ spacing: { before: 300 } }));
children.push(heading("Mejoras en Titulo"));
children.push(sectionDivider());
(data.title_suggestions || []).forEach(s => children.push(bulletItem(s)));

// Sugerencias de descripción
children.push(new Paragraph({ children: [new PageBreak()] }));
children.push(heading("Mejoras en Descripcion"));
children.push(sectionDivider());
(data.description_suggestions || []).forEach(s => children.push(bulletItem(s)));

// Sugerencias de fotos
children.push(new Paragraph({ spacing: { before: 300 } }));
children.push(heading("Mejoras en Fotos"));
children.push(sectionDivider());
(data.photo_suggestions || []).forEach(s => children.push(bulletItem(s)));

// Recomendaciones generales
children.push(new Paragraph({ children: [new PageBreak()] }));
children.push(heading("Recomendaciones Generales"));
children.push(sectionDivider());
(data.general_suggestions || []).forEach(s => children.push(bulletItem(s)));

// Build document
const doc = new Document({
    styles: {
        default: { document: { run: { font: "Arial", size: 22 } } },
        paragraphStyles: [
            {
                id: "Heading1", name: "Heading 1", basedOn: "Normal", next: "Normal", quickFormat: true,
                run: { size: 36, bold: true, font: "Arial", color: PRIMARY_DARK },
                paragraph: { spacing: { before: 360, after: 120 }, outlineLevel: 0 }
            },
            {
                id: "Heading2", name: "Heading 2", basedOn: "Normal", next: "Normal", quickFormat: true,
                run: { size: 28, bold: true, font: "Arial", color: PRIMARY },
                paragraph: { spacing: { before: 240, after: 120 }, outlineLevel: 1 }
            }
        ]
    },
    numbering: {
        config: [
            {
                reference: "bullets",
                levels: [{
                    level: 0, format: LevelFormat.BULLET, text: "\u2022", alignment: AlignmentType.LEFT,
                    style: { paragraph: { indent: { left: 720, hanging: 360 } } }
                }]
            }
        ]
    },
    sections: [{
        properties: {
            page: {
                size: { width: 12240, height: 15840 },
                margin: { top: 1440, right: 1440, bottom: 1440, left: 1440 }
            }
        },
        headers: {
            default: new Header({
                children: [new Paragraph({
                    alignment: AlignmentType.RIGHT,
                    children: [new TextRun({ font: "Arial", size: 18, color: "94A3B8", text: "Alojando BOT - Informe Comparativo" })]
                })]
            })
        },
        footers: {
            default: new Footer({
                children: [new Paragraph({
                    alignment: AlignmentType.CENTER,
                    children: [
                        new TextRun({ font: "Arial", size: 18, color: "94A3B8", text: "Pagina " }),
                        new TextRun({ font: "Arial", size: 18, color: "94A3B8", children: [PageNumber.CURRENT] })
                    ]
                })]
            })
        },
        children
    }]
});

function createTable(rows, columnWidths) {
    const tableWidth = columnWidths.reduce((a, b) => a + b, 0);
    return new Table({
        width: { size: tableWidth, type: WidthType.DXA },
        columnWidths,
        rows: rows.map((row, rowIdx) =>
            new TableRow({
                children: row.map((cell, colIdx) =>
                    new TableCell({
                        borders,
                        width: { size: columnWidths[colIdx], type: WidthType.DXA },
                        shading: rowIdx === 0
                            ? { fill: PRIMARY, type: ShadingType.CLEAR }
                            : rowIdx === 1 && rows.length > 2
                                ? { fill: "DBEAFE", type: ShadingType.CLEAR }
                                : { fill: rowIdx % 2 === 0 ? "F8FAFC" : "FFFFFF", type: ShadingType.CLEAR },
                        margins: cellMargins,
                        children: [new Paragraph({
                            children: [new TextRun({
                                font: "Arial",
                                size: rowIdx === 0 ? 20 : 20,
                                bold: rowIdx === 0 || rowIdx === 1,
                                color: rowIdx === 0 ? "FFFFFF" : "1E293B",
                                text: cell
                            })]
                        })]
                    })
                )
            })
        )
    });
}

Packer.toBuffer(doc).then(buffer => {
    fs.writeFileSync(outputPath, buffer);
    console.log(`Informe DOCX generado: ${outputPath}`);
}).catch(err => {
    console.error("Error generando DOCX:", err);
    process.exit(1);
});
