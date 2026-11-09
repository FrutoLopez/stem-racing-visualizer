# STEM Racing Results Visualizer 🏎️🏁

Visualizador interactivo en tiempo real desarrollado en **Python Streamlit** para el registro de tiempos en pista, clasificación oficial y ceremonia de podio de competencias **STEM Racing (F1 in Schools)**.

Cumple con el reglamento oficial **STEM Racing Competition Regulations (C9.5 – C9.8)** y los lineamientos de marca **STEM Racing Brand Guidelines V1.3**.

---

## 🚀 Cómo Iniciar la Aplicación

```powershell
# 1. Activar el entorno virtual (Windows PowerShell)
.\.venv\Scripts\Activate.ps1

# 2. Iniciar Streamlit
streamlit run app.py
```

La aplicación estará disponible en: **`http://localhost:8501`**.

---

## 🧭 Pantallas Principales

### 1. ⏱️ Tiempos y Resultados en Pista
Consta de 4 pestañas de visualización sincronizadas automáticamente cada segundo:
* **⏱️ Tiempos por Equipos:** Tabla a dos columnas en orden oficial (`Equipos.csv`) mostrando el **Mejor Tiempo Total** y el **Tiempo de Carro** de cada equipo.
* **⚔️ Duelos Cara a Cara:** Comparativa manga a manga (Carreras 1 a 4) para cada uno de los 5 enfrentamientos oficiales, incluyendo tiempos de reacción, pista, total y tarjetas de récords.
* **🏎️ Tiempo de Carro (C9.6 Time Trial):** Clasificación ordenada por el promedio del 2do y 3er mejor tiempo de pista (con regla oficial de reemplazo por DNF) y diferencia (`+0.xxx s`) respecto al líder.
* **🚀 Tiempo Más Rápido (C9.5 Reaction Race):** Clasificación ordenada por el tiempo total más rápido (reacción + pista) y diferencia respecto al líder.

### 2. 🏆 Ceremonia de Podio Oficial
Presentación animada paso a paso libre de distracciones:
* **Paso 0 (Intro):** Resumen del campeonato (990 puntos máximos en las 6 áreas oficiales).
* **Pasos 1 a 3 (3er, 2do y 1er Lugar):** Revelación progresiva que muestra primero los puntajes en las 6 categorías y finalmente revela con animación al equipo ganador y su puntaje acumulado.
* **Paso 4 (Podio Completo):** Pedestales 3D para el Top 3 y tablas clasificatorias para las posiciones **#4 a #10**.

### 3. 📝 Pantalla de Edición y Registro
* Registro en vivo por enfrentamiento oficial (1 vs 2, 3 vs 4, 5 vs 6, 7 vs 8, 9 vs 10) y número de carrera (1 a 4).
* Casillas para marcar **❌ DNF** (C9.7) y **🚦 False Start** (C9.8).
* **🎲 Test Mode:** Generador de datos de prueba aleatorios por carrera.
* **📋 Monitor General del Torneo:** Vista consolidada de los 10 equipos y sus 4 carreras.
* **🕒 Historial de Registros CSV y Editor de Grilla:** Registro auditable (`live_race_data.csv`) con `id` secuencial y `timestamp`.

---

## 📝 Carga de Puntajes de Jueces (`STEM RACING - COMPETITION JUDGING BREAKDOWN`)

Desde la barra lateral (**📝 Rúbrica de Jueces**), puedes subir uno o múltiples archivos `.xlsx` o `.csv` con el formato oficial **`STEM RACING - COMPETITION JUDGING BREAKDOWN`**:
* Identifica automáticamente al equipo por `Team Name:`, `Team Number:` (01–10), `School:` o nombre de archivo.
* Extrae los puntos otorgados (`Awarded Points`) en las 5 categorías evaluadas por jueces (770 pts máx.):
  1. **Especificaciones y Escrutinio** (`Specification and Scrutineering Judging` — máx. 170 pts)
  2. **Diseño e Ingeniería** (`Design and Engineering Judging` — máx. 180 pts)
  3. **Gestión de Proyecto** (`Enterprise Judging` — máx. 160 pts)
  4. **Presentación Verbal** (`Verbal Presentation Judging` — máx. 160 pts)
  5. **Identidad de Marca** (`Brand Identity Judging` — máx. 100 pts)
* Incluye respaldo automático leyendo sub-categorías y hojas de *Scorecards* individuales si el archivo `.xlsx` contiene fórmulas sin caché.
* Los puntajes cargados o editados manualmente se guardan automáticamente en `judge_scores.csv`.
