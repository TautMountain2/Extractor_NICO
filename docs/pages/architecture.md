\page architecture_page Arquitectura

# Arquitectura del sistema

La solución se basa en una arquitectura de responsabilidades separadas:

1. **Fuente / extracción**
2. **Normalización / ETL**
3. **Persistencia local**
4. **Interfaz y exportación**

\dotfile docs/diagrams/architecture.dot "Arquitectura general"

## Decisión principal de almacenamiento

Se utiliza **DuckDB** en lugar de una base servidor tradicional porque:

- es embebido y local
- no requiere administración de servicio
- tiene excelente desempeño analítico
- exporta y lee fácilmente CSV y Parquet
- simplifica el despliegue en un solo equipo

## Escalabilidad

Aunque el objetivo operativo es NICO (10 dígitos), el modelo guarda también jerarquías superiores:

- hs2
- hs4
- hs6
- fraccion8
- nico10

Esto permite ampliar el proyecto sin rediseñar la base.
