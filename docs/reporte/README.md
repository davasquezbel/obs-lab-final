# Generador del reporte final (Word)

`build.js` genera el reporte ejecutivo con [docx](https://www.npmjs.com/package/docx).
Requiere en `img/` las figuras (diagrama, gráfica de caos y capturas de la bitácora en JPG/PNG)
y un `validation.json` con el texto de accionabilidad de cada experimento.

```bash
npm install docx@9
node build.js Reporte_Final_Observabilidad.docx
```
