import streamlit as st

from api import (
    get_starred_companies,
    add_starred_company,
    delete_starred_company,
    update_starred_company,
)


@st.cache_data(ttl=30)
def _fetch_starred(search: str) -> list[dict]:
    return get_starred_companies(search=search or None)


def render_starred_tab():
    st.markdown('<div class="section-title">Starred Companies</div>', unsafe_allow_html=True)

    # ── Add form ──────────────────────────────────────────────────────────────
    with st.expander("➕ Add company", expanded=False):
        with st.form("add_starred_form", clear_on_submit=True):
            name_col, url_col = st.columns(2)
            with name_col:
                name = st.text_input("Company name *", placeholder="e.g. Google")
            with url_col:
                url = st.text_input("Careers page URL", placeholder="https://careers.company.com")
            notes = st.text_area("Notes", placeholder="Why you like this company…", height=68)
            submitted = st.form_submit_button("⭐ Add Company", use_container_width=True)

        if submitted:
            if not name.strip():
                st.error("Company name is required.")
            else:
                result = add_starred_company(
                    company_name=name.strip(),
                    careers_url=url.strip() or None,
                    notes=notes.strip() or None,
                )
                if result is None:
                    st.error(f'"{name}" is already starred or could not be added.')
                else:
                    st.success(f'⭐ "{name}" added.')
                    st.cache_data.clear()
                    st.rerun()

    # ── Search ────────────────────────────────────────────────────────────────
    search = st.text_input(
        "Search",
        placeholder="Filter starred companies…",
        label_visibility="collapsed",
        key="starred_search",
    )

    companies = _fetch_starred(search)

    if not companies:
        st.info("No starred companies yet. Add one above.")
        return

    n = len(companies)
    st.markdown(
        f'<div class="starred-count">{n} compan{"y" if n == 1 else "ies"}</div>',
        unsafe_allow_html=True,
    )

    # ── 1-column card list ────────────────────────────────────────────────────
    for company in companies:
        _render_company_card(company)


def _render_company_card(company: dict):
    cid = company["id"]
    name = company["company_name"].title()
    notes = company.get("notes") or ""
    careers_url = company.get("careers_url") or ""
    created = (company.get("created_at") or "")[:10]
    edit_key = f"starred_editing_{cid}"

    with st.container():
        # Header: name + date badge
        notes_html = f'<p class="starred-notes">{notes}</p>' if notes else ""
        url_placeholder = (
            "" if careers_url else '<span class="starred-no-url">No careers URL set</span>'
        )
        st.markdown(
            f"""
            <div class="starred-card-header">
                <span class="starred-company-name">⭐ {name}</span>
                <span class="starred-date-badge">{created}</span>
            </div>
            {notes_html}
            {url_placeholder}
            """,
            unsafe_allow_html=True,
        )

        if careers_url:
            st.markdown(f"[🔗 Careers page]({careers_url})")

        # Action row: large spacer + Edit + Remove (pushed to far right)
        _, edit_col, del_col = st.columns([12, 1, 1])
        editing = st.session_state.get(edit_key, False)
        with edit_col:
            edit_label = "✖ Cancel" if editing else "✏️ Edit"
            if st.button(edit_label, key=f"edit_btn_{cid}", use_container_width=True):
                st.session_state[edit_key] = not editing
                st.rerun()
        with del_col:
            if st.button("🗑️", key=f"del_starred_{cid}", type="primary", use_container_width=True):
                delete_starred_company(cid)
                st.cache_data.clear()
                st.rerun()

        # Inline edit form (shown only when editing)
        if editing:
            with st.form(f"edit_starred_form_{cid}"):
                new_url = st.text_input("Careers page URL", value=careers_url)
                new_notes = st.text_area("Notes", value=notes, height=80)
                if st.form_submit_button("💾 Save", use_container_width=True):
                    update_starred_company(
                        cid,
                        careers_url=new_url.strip() or None,
                        notes=new_notes.strip() or None,
                    )
                    st.session_state.pop(edit_key, None)
                    st.cache_data.clear()
                    st.rerun()

        st.markdown('<div class="starred-card-divider"></div>', unsafe_allow_html=True)
