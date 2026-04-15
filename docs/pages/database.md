\page database_page Base de datos

# Modelo de datos

La tabla principal es `fact_trade_monthly`.

## Clave lógica

- date_month
- flow_code
- country_name
- tariff_code
- source_code

## Variables analíticas clave

- `value_usd`
- `quantity`
- `country_iso3`
- `tariff_level`
- `hs2`, `hs4`, `hs6`, `fraccion8`, `nico10`

## Auditoría

- `load_run`
- `etl_file_registry`
- `etl_error_log`
- `fact_trade_monthly_history`

\dotfile docs/diagrams/data_model.dot "Modelo lógico simplificado"
