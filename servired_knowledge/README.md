# SERVIRED Knowledge - Documentos para Sofía

Carpeta de carga para la base de conocimiento SERVIRED.

## Uso

```bash
python -m app.services.document_ingester servired_knowledge/
```

## Estructura

Colocá los archivos en esta carpeta o en subcarpetas organizadas por categoría:

```
servired_knowledge/
  planes/
    plan_medimax.md
    plan_gold.txt
  coberturas/
    coberturas_generales.pdf
  beneficios/
    descuentos_2024.xlsx
  objeciones/
    respuestas_objeciones.txt
```

## Formatos soportados

| Extensión | Descripción |
|-----------|-------------|
| `.md`     | Markdown |
| `.txt`    | Texto plano |
| `.pdf`    | PDF (requiere PyPDF2 o pdfplumber) |
| `.xlsx`   | Excel (requiere openpyxl) |

## Categorías

La categoría se detecta automáticamente:
- **Por subcarpeta**: el nombre de la subcarpeta es la categoría
- **Por nombre de archivo**: se busca la keyword en el nombre

Categorías válidas: `planes`, `coberturas`, `beneficios`, `objeciones`, `cierres`, `precios`, `argumentos`, `informacion`

## Ejemplo rápido

1. Crear un archivo `planes_SERVIRED.txt` con información de planes
2. Ejecutar: `python -m app.services.document_ingester servired_knowledge/`
3. Sofía ya puede consultar esos planes en conversaciones
