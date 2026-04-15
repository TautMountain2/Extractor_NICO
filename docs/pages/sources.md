\page sources_page Fuentes y estrategia de extracción

# Fuentes

La fuente primaria prevista es el cubo interactivo de INEGI/BCMM, porque permite cruces por:

- país
- flujo
- año
- mes
- tarifa / fracción / NICO
- valor en dólares
- cantidad

## Estrategia recomendada

### Fuente primaria
- Cubo interactivo BCMM de INEGI.

### Fuente secundaria de contraste
- Directorio de fuentes estadísticas de SNICE.
- Otras consultas de Banxico o SIAVI para validación de consistencia agregada.

## Modo de operación

### 1. Automatizado
Playwright navega el cubo y descarga archivos en formato tabular.

### 2. Manual robusto
Si el portal cambia, el usuario exporta bloques desde la interfaz oficial y deposita los archivos en `data/inbox/`. Luego el ETL los ingiere.

Este segundo camino evita que un cambio visual del sitio rompa todo el sistema.
