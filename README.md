# STEM Racing Results Visualizer 🏎️🏁

Visualizador interactivo desarrollado en **Python Streamlit** para el análisis, cálculo y presentación de resultados de competencias **STEM Racing (F1 in Schools)**.

El sistema procesa automáticamente los datos del archivo Excel (`Racing Score Calculator.xlsx`) y reproduce cada diapositiva del archivo de diseño (`Mockups.pptx`) como una pestaña interactiva dedicada.

---

## 🚀 Cómo Iniciar la Aplicación

Para ejecutar la aplicación localmente:

```bash
# 1. Activar el entorno virtual
source .venv/bin/activate

# 2. Iniciar Streamlit
streamlit run app.py
```

La aplicación se abrirá en tu navegador en: **`http://localhost:8501`**.

---

## 📑 Estructura de Pestañas (Correspondencia con `Mockups.pptx`)

| Pestaña en Streamlit | Diapositiva Mockup | Descripción y Funcionalidad |
| :--- | :--- | :--- |
| **🏁 Slide 1: Fastest Cars Broadcast** | Diapositiva 1 | Tabla de clasificación estilo transmisión televisiva del *Aramco STEM Racing World Finals* con deltas (+0.xxx s), insignias de bandera a cuadros y filtros de búsqueda en vivo. |
| **⏱️ Slide 2: Tiempos Más Rápidos** | Diapositiva 2 | Distribución en dos columnas (Equipo 1-5 a la izquierda, 6-10 a la derecha) mostrando el tiempo récord de cada equipo y barras comparativas. |
| **⚔️ Slide 3: Duelo Cara a Cara** | Diapositiva 3 | Comparativa manga a manga (Carreras 1 a 4) entre dos equipos seleccionables con tiempos de reacción, tiempos de pista y tiempos totales, resaltando al ganador de cada manga. |
| **🏎️ Slide 4: Mejores Tiempos de Carrera** | Diapositiva 4 | Tabla del TOP 3 y clasificación completa basada en el promedio de los 2 tiempos intermedios de pista (Col G de Excel) y cálculo oficial de puntos (Col L). |
| **🚀 Slide 5: Mejores Tiempos de Carro** | Diapositiva 5 | Tabla del TOP 3 y clasificación completa basada en el tiempo total más rápido (Col H de Excel) y cálculo oficial de puntos (Col S). |
| **🥉 Slide 6: 3er Lugar** | Diapositiva 6 | Ficha de revelación de medalla de bronce con desglose en dos tablas de las 6 categorías evaluadas y gráfico de radar de rendimiento. |
| **🥈 Slide 7: 2do Lugar** | Diapositiva 7 | Ficha de revelación de medalla de plata con desglose de puntaje y gráfico de radar. |
| **🥇 Slide 8: 1er Lugar** | Diapositiva 8 | Ficha de revelación del Campeón con medalla de oro, puntaje acumulado y efectos de celebración. |
| **🏆 Slide 9: Podio Oficial** | Diapositiva 9 | Podio 3D olímpico interactivo (1er, 2do y 3er lugar), tabla oficial del podio, clasificación general completa y botón interactivo de fanfarria/confeti. |

---

## 📐 Lógica de Cálculos (Hojas de Excel)

### 1. Datos sin procesar (Columnas A a D)
* **Columna A:** Nombre del equipo (`Team 1`, `Team 2`, ...). Cada equipo corre 4 mangas.
* **Columna B:** Tiempo de Reacción del piloto (segundos).
* **Columna C:** Tiempo de Pista / Carrera del coche (segundos).
* **Columna D:** Tiempo Total ($D = B + C$).

### 2. Organización de Datos (Columnas E a H)
* **Columna E:** Tiempos de carrera ordenados de menor a mayor (`SORT(C3:C6)`).
* **Columna F:** Tiempos totales ordenados de menor a mayor (`SORT(D3:D6)`).
* **Columna G (Tiempo Promedio de Carrera):** Promedio de los dos tiempos intermedios:
  $$\text{Promedio} = \frac{E_2 + E_3}{2} = \text{AVERAGE}(E4:E5)$$
  *(Descarta el tiempo más rápido y el más lento para medir consistencia).*
* **Columna H (Tiempo Total Más Rápido):** Menor tiempo total entre las 4 mangas:
  $$\text{Mínimo Total} = \min(D_1, D_2, D_3, D_4)$$

### 3. Mejores Tiempos de Carrera y Puntos (Columnas J a M)
* **Columna J:** Tiempos promedio (Col G) ordenados ascendentemente.
* **Columna K:** Equipo correspondiente (`XLOOKUP`).
* **Columna M (Tiempo Base $M3$):** 115% del tiempo del 3er lugar ($M3 = J5 \times 1.15$).
* **Columna L (Puntos):**
  * 1er Lugar: **110 puntos**
  * 2do Lugar: **105 puntos**
  * 3er Lugar: **100 puntos**
  * 4to Lugar en adelante:
    $$\text{Puntos} = \begin{cases} 20 & \text{si } Tiempo > M3 \\ \text{ROUND}\left(20 + \frac{80}{M3 - J5} \times (M3 - Tiempo)\right) & \text{si } Tiempo \le M3 \end{cases}$$

### 4. Mejores Tiempos de Carro y Puntos (Columnas Q a T)
* **Columna Q:** Tiempos totales más rápidos (Col H) ordenados ascendentemente.
* **Columna R:** Equipo correspondiente (`XLOOKUP`).
* **Columna T (Tiempo Base $T3$):** 120% del tiempo del 3er lugar ($T3 = Q5 \times 1.20$).
* **Columna S (Puntos):**
  * 1er Lugar: **110 puntos**
  * 2do Lugar: **105 puntos**
  * 3er Lugar: **100 puntos**
  * 4to Lugar en adelante:
    $$\text{Puntos} = \begin{cases} 5 & \text{si } Tiempo > T3 \\ \text{ROUND}\left(5 + \frac{95}{T3 - Q3} \times (T3 - Tiempo)\right) & \text{si } Tiempo \le T3 \end{cases}$$

---

## 🎨 Personalización y Carga de Nuevos Archivos

* **Carga de Archivos:** Puedes arrastrar y soltar cualquier nuevo archivo `.xlsx` desde la barra lateral.
* **Edición de Rúbricas:** Desde el menú desplegable en la barra lateral puedes ajustar las calificaciones de los jueces en las 6 categorías evaluadas:
  1. Identidad de Marca
  2. Presentación Verbal
  3. Carrera (calculada automáticamente de la pista)
  4. Especificaciones y Escrutinio
  5. Diseño e Ingeniería
  6. Gestión de Proyecto
* El podio final y las fichas de los lugares 1, 2 y 3 se actualizarán instantáneamente con los nuevos totales.
