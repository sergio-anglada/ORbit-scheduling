import streamlit as st
import time
from ortools.sat.python import cp_model

st.set_page_config(page_title="Optimizador de Turnos — Campus", layout="wide")
st.title("Optimizador de Turnos — Conserjes Campus")
st.caption("Basado en modelo de investigación operativa real")

# ─── Parámetros en sidebar ───────────────────────────────────────────────────
with st.sidebar:
    st.header("Parámetros")
    n_trabajadores = st.number_input("Número de trabajadores", 2, 20, 6)
    n_edificios    = st.number_input("Número de edificios",    1, 10, 2)
    n_semanas      = st.slider("Semanas a planificar", 1, 30, 15)
    dif_edificios  = st.slider("Diferencia máxima entre edificios (Δ)", 0, 10, 2)
    timeout        = st.slider("Tiempo máximo de resolución (s)", 10, 1800, 300)

    st.divider()
    st.caption("Turnos: 0 = Mañana, 1 = Tarde")
    cob_manana = st.number_input("Conserjes mañana por edificio", 1, 5, 2)
    cob_tarde  = st.number_input("Conserjes tarde por edificio",  1, 5, 1)

resolver = st.button("Resolver", type="primary", use_container_width=True)

# ─── Solver ──────────────────────────────────────────────────────────────────
if resolver:

    # ── Validación previa ────────────────────────────────────────────────
    demanda_total = n_edificios * (cob_manana + cob_tarde)
    if n_trabajadores < demanda_total:
        st.error(
            f"❌ No hay suficientes trabajadores para cubrir todos los turnos. "
            f"Con {n_edificios} edificio(s), {cob_manana} de mañana y {cob_tarde} de tarde por edificio, "
            f"se necesitan exactamente **{demanda_total} trabajadores**, pero solo hay **{n_trabajadores}**."
        )
        st.stop()
    elif n_trabajadores > demanda_total:
        st.error(
            f"❌ Hay más trabajadores que huecos disponibles. "
            f"Con {n_edificios} edificio(s), {cob_manana} de mañana y {cob_tarde} de tarde por edificio, "
            f"se necesitan exactamente **{demanda_total} trabajadores**, pero hay **{n_trabajadores}**."
        )
        st.stop()

    I = range(n_trabajadores)
    E = range(n_edificios)
    K = range(2)          # 0=mañana, 1=tarde
    T = range(n_semanas)

    model  = cp_model.CpModel()
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = timeout
    solver.parameters.log_search_progress = False

    # Variables principales
    x = {}
    for i in I:
        for e in E:
            for k in K:
                for t in T:
                    x[i,e,k,t] = model.new_bool_var(f"x_{i}_{e}_{k}_{t}")

    # Variables auxiliares: coincidencia entre trabajadores
    y = {}
    for i in I:
        for j in I:
            if i != j:
                for e in E:
                    for t in T:
                        y[i,j,e,t] = model.new_bool_var(f"y_{i}_{j}_{e}_{t}")

    # z_max: máximo de semanas que coinciden dos trabajadores
    z_max = model.new_int_var(0, n_semanas * n_edificios, "z_max")


    # ── Restricciones ──────────────────────────────────────────────────────

    # R1: Cada trabajador hace exactamente 1 turno por semana (en algún edificio)
    for i in I:
        for t in T:
            model.add(sum(x[i,e,k,t] for e in E for k in K) == 1)

    # R2: Cobertura mínima mañana por edificio
    for e in E:
        for t in T:
            model.add(sum(x[i,e,0,t] for i in I) == cob_manana)

    # R3: Cobertura mínima tarde por edificio
    for e in E:
        for t in T:
            model.add(sum(x[i,e,1,t] for i in I) == cob_tarde)

    # R4: Máximo 3 semanas en el mismo edificio en ventana de 4
    for i in I:
        for e in E:
            for t in range(n_semanas - 3):
                model.add(
                    sum(x[i,e,k,t+d] for k in K for d in range(4)) <= 3
                )

    # R5: Tras turno de tarde, siguiente turno debe ser de mañana
    for i in I:
        for t in range(n_semanas - 2):
            model.add(
                sum(x[i,e,1,t] for e in E) + 1 <=
                sum(x[i,e,0,t+1] + x[i,e,0,t+2] for e in E)
            )

    # R6: Rotación de tarde entre edificios (si n_edificios >= 2)
    if n_edificios >= 2:
        for i in I:
            for t in range(n_semanas - 3):
                model.add(x[i,0,1,t] == x[i,1,1,t+3])
                model.add(x[i,1,1,t] == x[i,0,1,t+3])

    # R7: Definición de y (coincidencia en mañana)
    for i in I:
        for j in I:
            if i != j:
                for e in E:
                    for t in T:
                        model.add(y[i,j,e,t] <= x[i,e,0,t])
                        model.add(y[i,j,e,t] <= x[j,e,0,t])
                        model.add(y[i,j,e,t] >= x[i,e,0,t] + x[j,e,0,t] - 1)

    # R8: z_max = max coincidencias entre cualquier par
    for i in I:
        for j in I:
            if i != j:
                model.add(
                    sum(y[i,j,e,t] for e in E for t in T) <= z_max
                )

    # R9: Equilibrio entre edificios por trabajador (todos los pares)
    d_plus  = {}
    d_minus = {}
    if n_edificios >= 2:
        for i in I:
            for e1 in E:
                for e2 in E:
                    if e1 < e2:
                        d_plus[i,e1,e2]  = model.new_int_var(0, n_semanas, f"dp_{i}_{e1}_{e2}")
                        d_minus[i,e1,e2] = model.new_int_var(0, n_semanas, f"dm_{i}_{e1}_{e2}")
                        model.add(
                            sum(x[i,e1,k,t] for k in K for t in T) -
                            sum(x[i,e2,k,t] for k in K for t in T) ==
                            d_plus[i,e1,e2] - d_minus[i,e1,e2]
                        )
                        model.add(d_plus[i,e1,e2]  <= dif_edificios)
                        model.add(d_minus[i,e1,e2] <= dif_edificios)

    # ── Objetivo: minimizar máximo de coincidencias ─────────────────────
    model.minimize(z_max)

    # ── Resolver ────────────────────────────────────────────────────────
    progress = st.progress(0, text="Resolviendo...")
    t0 = time.time()

    # Simulamos progreso mientras OR-Tools trabaja
    import threading
    resultado_container = [None]

    def run_solver():
        resultado_container[0] = solver.solve(model)

    thread = threading.Thread(target=run_solver)
    thread.start()

    while thread.is_alive():
        elapsed = time.time() - t0
        pct = min(int(elapsed / timeout * 90), 90)
        progress.progress(pct, text=f"Resolviendo... {elapsed:.0f}s")
        time.sleep(0.5)

    thread.join()
    progress.progress(100, text="Listo")
    elapsed_total = time.time() - t0

    status = resultado_container[0]
    status_name = solver.status_name(status)

    # ── Resultados ──────────────────────────────────────────────────────
    st.divider()

    if status in [cp_model.OPTIMAL, cp_model.FEASIBLE]:

        obj_val = solver.objective_value
        es_optimo = status == cp_model.OPTIMAL

        # Métricas principales
        col1, col2, col3, col4 = st.columns(4)
        col1.metric("Estado", "Óptimo" if es_optimo else "Factible")
        col2.metric("Máx. coincidencias", int(obj_val))
        col3.metric("Tiempo", f"{elapsed_total:.1f}s")
        col4.metric("Semanas", n_semanas)

        if not es_optimo:
            st.warning("Solución factible (no óptima) — se alcanzó el límite de tiempo.")

        # Extraer solución
        vals_x = {(i,e,k,t): solver.value(x[i,e,k,t])
                  for i in I for e in E for k in K for t in T}

        
        # ── Resumen por trabajador ──────────────────────────────────
        nombres_edificios = [f"Edificio {e+1}" for e in E]
        st.subheader("Resumen por trabajador")

        import pandas as pd
        rows = []
        for i in I:
            sem_edificios = {e: sum(vals_x[i,e,k,t] for k in K for t in T)
                             for e in E}
            rows.append({
                "Trabajador": f"Trabajador {i+1}",
                **{nombres_edificios[e]: int(sem_edificios[e]) for e in E},
                "Total semanas": int(sum(sem_edificios.values()))
            })

        st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

        # ── Coincidencias entre trabajadores ───────────────────────
        st.subheader("Semanas que coinciden en mañana")

        vals_y = {(i,j,e,t): solver.value(y[i,j,e,t])
                  for i in I for j in I if i != j
                  for e in E for t in T}

        coin_rows = []
        for i in I:
            for j in I:
                if i < j:
                    total = sum(vals_y[i,j,e,t] for e in E for t in T)
                    coin_rows.append({
                        "Par": f"T{i+1} — T{j+1}",
                        "Semanas coincidiendo": int(total),
                        "¿Es el máximo?": "⚠️ Sí" if int(total) == int(obj_val) else ""
                    })

        df_coin = pd.DataFrame(coin_rows).sort_values(
            "Semanas coincidiendo", ascending=False
        )
        st.dataframe(df_coin, use_container_width=True, hide_index=True)

        # ── Cuadrante visual ───────────────────────────────────────
        st.subheader("Cuadrante completo")

        COLORES = [
            "#4e79a7","#f28e2b","#e15759","#76b7b2","#59a14f",
            "#edc948","#b07aa1","#ff9da7","#9c755f","#bab0ac",
            "#1f77b4","#ff7f0e","#2ca02c","#d62728","#9467bd",
            "#8c564b","#e377c2","#7f7f7f","#bcbd22","#17becf",
        ]

        def color_texto(hex_bg):
            h = hex_bg.lstrip("#")
            r, g, b = int(h[0:2],16), int(h[2:4],16), int(h[4:6],16)
            luminancia = (0.299*r + 0.587*g + 0.114*b) / 255
            return "#000000" if luminancia > 0.5 else "#ffffff"

        def celda(trabajadores):
            if not trabajadores:
                return "<td style='padding:4px 8px;'></td>"
            partes = []
            for i in trabajadores:
                bg = COLORES[i % len(COLORES)]
                fg = color_texto(bg)
                partes.append(
                    f"<span style='background:{bg};color:{fg};"
                    f"border-radius:4px;padding:2px 6px;"
                    f"margin:1px;display:inline-block;font-size:0.85em;'>"
                    f"T{i+1}</span>"
                )
            return "<td style='padding:4px 8px;'>" + " ".join(partes) + "</td>"

        cabecera_cols = "<th style='padding:4px 8px;'>Semana</th><th style='padding:4px 8px;'>Turno</th>"
        for e in E:
            cabecera_cols += f"<th style='padding:4px 8px;'>{nombres_edificios[e]}</th>"

        filas_html = ""
        for t in T:
            bg_fila_m = "#f0f4f8" if t % 2 == 0 else "#ffffff"
            bg_fila_t = "#dce8f0" if t % 2 == 0 else "#eef4f8"

            fila_m = f"<tr style='background:{bg_fila_m};'>"
            fila_m += f"<td rowspan='2' style='padding:4px 8px;font-weight:bold;vertical-align:middle;'>S{t+1}</td>"
            fila_m += f"<td style='padding:4px 8px;font-size:0.8em;color:#555;'>🌅 Mañana</td>"
            for e in E:
                trabajadores_celda = [i for i in I if vals_x[i,e,0,t] == 1]
                fila_m += celda(trabajadores_celda)
            fila_m += "</tr>"

            fila_t = f"<tr style='background:{bg_fila_t};'>"
            fila_t += f"<td style='padding:4px 8px;font-size:0.8em;color:#555;'>🌆 Tarde</td>"
            for e in E:
                trabajadores_celda = [i for i in I if vals_x[i,e,1,t] == 1]
                fila_t += celda(trabajadores_celda)
            fila_t += "</tr>"

            filas_html += fila_m + fila_t

        leyenda = "<div style='margin-top:12px;display:flex;flex-wrap:wrap;gap:8px;'>"
        for i in I:
            bg = COLORES[i % len(COLORES)]
            fg = color_texto(bg)
            leyenda += (
                f"<span style='background:{bg};color:{fg};"
                f"border-radius:4px;padding:3px 10px;font-size:0.85em;'>"
                f"Trabajador {i+1}</span>"
            )
        leyenda += "</div>"

        tabla_html = f"""
        <div style='overflow-x:auto;'>
        <table style='border-collapse:collapse;width:100%;font-size:0.9em;'>
          <thead>
            <tr style='background:#2c3e50;color:white;'>
              {cabecera_cols}
            </tr>
          </thead>
          <tbody>
            {filas_html}
          </tbody>
        </table>
        </div>
        {leyenda}
        """

        st.markdown(tabla_html, unsafe_allow_html=True)

        # ── Exportar ───────────────────────────────────────────────
        st.subheader("Exportar")
        csv = df_coin.to_csv(index=False)
        st.download_button(
            "Descargar coincidencias CSV",
            csv,
            "coincidencias.csv",
            "text/csv"
        )

    elif status == cp_model.INFEASIBLE:
        st.error("El problema es infeasible con los parámetros actuales. "
                 "Prueba a aumentar Δ o reducir la cobertura mínima.")
    else:
        st.warning(f"Estado: {status_name}. Prueba a aumentar el tiempo máximo.")
