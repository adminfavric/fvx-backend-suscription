"""Filtros Jinja2 disponibles dentro de los templates de email.

Cada proyecto que consume este backend puede agregar filtros propios acá
(formateo de moneda local, fechas relativas, etc.). Por default está vacío
para mantener la infraestructura agnóstica del producto.

Ejemplo de filtro custom:

    FILTERS = {
        "money": lambda v: f"${v:,.0f}",
        "phone_cl": lambda v: f"+56 {v[:1]} {v[1:5]} {v[5:]}",
    }

Y en el template:

    El total es {{ amount | money }}.
"""

FILTERS: dict = {
    # vacío por default — cada producto agrega los suyos.
}
