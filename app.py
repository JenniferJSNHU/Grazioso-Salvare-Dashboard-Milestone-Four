from math import isfinite
from pathlib import Path
import base64
import csv
import io
from dotenv import load_dotenv

# load saved environment variables for local development
load_dotenv(Path(__file__).resolve().parent / ".env")

import dash_leaflet as dl
import plotly.graph_objects as go
from dash import Dash, Input, Output, State, dash_table, dcc, html
from dash.exceptions import PreventUpdate
from CRUD_Python_Module import AnimalShelter
from animal_service import (
    TABLE_FILTER_FIELDS,
    build_table_query,
    rescue_query,
    validate_animal,
)
from staff_auth import enable_staff_auth

# rank eligible rescue candidates using the min-heap algorithm
from rescue_ranking import rank_candidates

# connect to the imported animal shelter database
db = AnimalShelter()

# retrieve the fields needed for records, analytics, and mapping
animal_fields = {
    "_id": 0,
    "animal_id": 1,
    "name": 1,
    "animal_type": 1,
    "breed": 1,
    "sex_upon_outcome": 1,
    "age_upon_outcome_in_weeks": 1,
    "location_lat": 1,
    "location_long": 1,
}
# retrieve animal type totals directly from MongoDB
animal_type_counts = db.aggregate_field_counts("animal_type")

# count the total number of animals and the number of dogs and cats
total_animals = db.count({})
total_dogs = db.count({"animal_type": "Dog"})
total_cats = db.count({"animal_type": "Cat"})

# count the number of animals matching each rescue category
rescue_counts = {
    name: db.count(rescue_query(name)) for name in ("water", "mountain", "disaster")
}

# define the columns to include in CSV exports
export_columns = [
    ("Animal ID", "animal_id"),
    ("Name", "name"),
    ("Type", "animal_type"),
    ("Breed", "breed"),
    ("Sex", "sex_upon_outcome"),
    ("Age (Weeks)", "age_upon_outcome_in_weeks"),
]

# initialize the Dash app
app = Dash(__name__)
app.title = "Grazioso Salvare | Dashboard"

# expose the Flask server to the production WSGI runner
server = app.server

# enable staff authentication for record creation and editing
enable_staff_auth(app.server)


# embed the Grazioso Salvare logo in the sidebar
logo_path = Path(__file__).resolve().parent / "Grazioso Salvare Logo.png"
if logo_path.exists():
    encoded_logo = base64.b64encode(logo_path.read_bytes()).decode("ascii")
    sidebar_logo = html.Img(
        src=f"data:image/png;base64,{encoded_logo}",
        alt="Grazioso Salvare logo",
        style={
            "width": "84px",
            "maxHeight": "95px",
            "objectFit": "contain",
            "marginBottom": "12px",
        },
    )
else:
    sidebar_logo = None


# create a reusable statistic card for the dashboard overview
def statistic_card(label, value, accent=False, value_id=None):
    return html.Div(
        [
            html.Div(label, className="stat-label"),
            html.Div(
                f"{value:,}",
                id=value_id,
                className="stat-value stat-accent" if accent else "stat-value",
            ),
        ],
        className="stat-card",
    )


# create a reusable navigation link for the sidebar
def navigation_link(label, path, component_id):
    return dcc.Link(
        label,
        href=path,
        id=component_id,
        className="nav-item",
        style={"display": "block", "textDecoration": "none"},
    )


def make_overview_chart(grouped_counts):
    # use MongoDB totals for the four most common animal types
    top_types = [(str(item["_id"]), item["count"]) for item in grouped_counts[:4]]
    # combine any remaining animal types into Other
    remaining = sum(item["count"] for item in grouped_counts[4:])
    # group all remaining types into a single "Other" category
    if remaining:
        top_types.append(("Other", remaining))
    fig = go.Figure()
    # only add a pie chart trace if there are records to display
    if top_types:
        # configure the pie chart with a donut hole and custom colors
        fig.add_trace(
            go.Pie(
                labels=[label for label, _ in top_types],
                values=[count for _, count in top_types],
                hole=0.65,
                marker={
                    "colors": ["#0d9488", "#224b63", "#79a9b1", "#a8d9cf", "#d3e3e7"]
                },
                textinfo="percent",
                hovertemplate="%{label}: %{value:,} (%{percent})<extra></extra>",
            )
        )
    # configure the chart layout for a clean dashboard appearance
    fig.update_layout(
        template="plotly_white",
        margin={"l": 8, "r": 105, "t": 6, "b": 6},
        height=240,
        showlegend=True,
        font={"family": "DM Sans, sans-serif", "color": "#243447"},
        legend={
            "orientation": "v",
            "x": 1.02,
            "y": 0.5,
            "xanchor": "left",
            "yanchor": "middle",
        },
    )
    return fig


# compare counts across the rescue categories
def make_rescue_chart(counts_by_rescue):
    categories = ["Water Rescue", "Mountain Rescue", "Disaster Tracking"]
    counts = [
        counts_by_rescue["water"],
        counts_by_rescue["mountain"],
        counts_by_rescue["disaster"],
    ]
    # only add a bar chart trace if there are records to display
    fig = go.Figure(
        go.Bar(
            x=counts,
            y=categories,
            orientation="h",
            marker_color="#0d9488",
            text=counts,
            textposition="outside",
            hovertemplate="%{y}: %{x:,} matching animals<extra></extra>",
        )
    )
    # configure the chart layout for a clean dashboard appearance
    fig.update_layout(
        template="plotly_white",
        height=350,
        margin={"l": 20, "r": 45, "t": 20, "b": 35},
        font={"family": "DM Sans, sans-serif", "color": "#243447"},
        xaxis={
            "title": "Matching animals",
            "rangemode": "tozero",
            "gridcolor": "#edf1f5",
        },
        yaxis={"title": "", "autorange": "reversed"},
        paper_bgcolor="white",
        plot_bgcolor="white",
    )
    return fig


# render the records table as a reusable dashboard component
def animal_table():
    return dash_table.DataTable(
        id="animal-table",
        columns=[
            {"name": "Animal ID", "id": "animal_id"},
            {"name": "Name", "id": "name"},
            {"name": "Type", "id": "animal_type"},
            {"name": "Breed", "id": "breed"},
            {"name": "Sex", "id": "sex_upon_outcome"},
            {"name": "Age (Weeks)", "id": "age_upon_outcome_in_weeks"},
        ],
        # load table records by page instead of loading the entire collection
        data=[],
        page_current=0,
        page_size=8,
        page_count=0,
        page_action="custom",
        # process sorting and filtering through mongodb
        sort_action="custom",
        sort_mode="single",
        sort_by=[],
        filter_action="custom",
        filter_options={"case": "insensitive"},
        filter_query="",
        # preserve single-animal selection for profiles and editing
        row_selectable="single",
        selected_rows=[],
        style_table={"overflowX": "auto"},
        style_cell={
            "textAlign": "left",
            "padding": "13px 12px",
            "fontFamily": "DM Sans, sans-serif",
            "fontSize": "13px",
            "minWidth": "95px",
            "maxWidth": "260px",
            "whiteSpace": "normal",
            "height": "auto",
            "border": "none",
            "borderBottom": "1px solid #edf1f5",
        },
        # style the header and data rows for a clean dashboard appearance
        style_header={
            "backgroundColor": "#f5f8fa",
            "fontWeight": "700",
            "color": "#41566a",
            "border": "none",
            "borderBottom": "1px solid #e4eaf0",
        },
        # style the selected row with a subtle highlight and border
        style_data={"backgroundColor": "white", "color": "#243447"},
        style_data_conditional=[
            {
                "if": {"state": "selected"},
                "backgroundColor": "#e6f5f2",
                "border": "1px solid #0d9488",
            },
        ],
    )


# helpers keep forms compact and their labels consistent
def form_field(label, field):
    return html.Div(
        [html.Label(label, className="form-label"), field], className="form-field"
    )


# one-page shelter operations dashboard
app.layout = html.Div(
    [
        dcc.Store(id="record-version", data=0),
        # sidebar links jump to sections instead of switching between pages
        html.Aside(
            [
                # display the logo and shelter name at the top of the sidebar
                html.Div(
                    [
                        sidebar_logo,
                        html.Div("Grazioso Salvare", className="sidebar-title"),
                        html.Div("ANIMAL RESCUE", className="sidebar-caption"),
                    ],
                    className="sidebar-brand",
                ),
                # provide a clear label for the workspace navigation links
                html.Div("WORKSPACE", className="nav-caption"),
                html.Nav(
                    [
                        html.A("Overview", href="#", className="nav-item active"),
                        html.A("Records", href="#records", className="nav-item"),
                        html.A("Analytics", href="#analytics", className="nav-item"),
                        html.A("Intake", href="#staff-tools", className="nav-item"),
                    ],
                ),
                # provide a clear label for the local database information
                html.Div(
                    [
                        html.Div("LOCAL DATABASE", className="sidebar-footer-title"),
                        html.Div("AAC · MongoDB", className="sidebar-footer-text"),
                    ],
                    className="sidebar-footer",
                ),
            ],
            className="sidebar",
        ),
        # main content area contains the overview, records, analytics, and staff tools
        html.Main(
            [
                html.A(id="overview"),
                # heading and context
                html.Header(
                    [
                        html.Div(
                            [
                                # provide a clear label for the dashboard heading
                                html.Div("SHELTER OPERATIONS", className="eyebrow"),
                                html.H1(
                                    "Animal Rescue Dashboard", className="page-title"
                                ),
                                # provide a clear label for the dashboard context
                                html.P(
                                    "Explore the shelter population, find rescue candidates, and review individual records.",
                                    className="page-subtitle",
                                ),
                            ],
                        ),
                        html.Div("●  Local database", className="status-pill"),
                    ],
                    className="page-header",
                ),
                # combine shelter statistics and population chart
                html.Section(
                    [
                        # display shelter statistics
                        html.Div(
                            [
                                html.H2("Shelter Snapshot", className="section-title"),
                                html.P(
                                    "Overview of current animal records and population by type.",
                                    className="card-subtitle",
                                ),
                                html.Div(
                                    [
                                        statistic_card(
                                            "Total Animal Records",
                                            total_animals,
                                            value_id="stats-total",
                                        ),
                                        statistic_card(
                                            "Dogs",
                                            total_dogs,
                                            accent=True,
                                            value_id="stats-dogs",
                                        ),
                                        statistic_card(
                                            "Cats", total_cats, value_id="stats-cats"
                                        ),
                                        statistic_card(
                                            "Matching Current Filters",
                                            total_animals,
                                            accent=True,
                                            value_id="stats-matching",
                                        ),
                                    ],
                                    className="snapshot-stats",
                                ),
                            ],
                        ),
                        # display shelter population chart
                        html.Div(
                            [
                                html.H2(
                                    "Shelter Population", className="section-title"
                                ),
                                html.P(
                                    "Share of records by animal type.",
                                    className="card-subtitle",
                                ),
                                dcc.Graph(
                                    id="overview-type-chart",
                                    figure=make_overview_chart(animal_type_counts),
                                    config={"displayModeBar": False},
                                ),
                            ],
                            className="snapshot-chart",
                        ),
                    ],
                    className="section-card snapshot-card",
                    style={"alignItems": "start"},
                ),
                # anchor records navigation above rescue filters
                html.A(
                    id="records", style={"display": "block", "scrollMarginTop": "10px"}
                ),
                # rescue filters control both the table and the chart/map
                html.Section(
                    [
                        html.Div(
                            [
                                html.H2(
                                    "Find Rescue Candidates", className="section-title"
                                ),
                                html.P(
                                    "Choose a rescue assignment to filter the records below.",
                                    className="card-subtitle",
                                ),
                            ],
                        ),
                        dcc.RadioItems(
                            id="rescue-filter",
                            options=[
                                {"label": "All Animals", "value": "reset"},
                                {"label": "Water Rescue", "value": "water"},
                                {"label": "Mountain Rescue", "value": "mountain"},
                                {"label": "Disaster Tracking", "value": "disaster"},
                            ],
                            value="reset",
                            className="rescue-options",
                            labelClassName="rescue-option",
                            inputClassName="rescue-input",
                        ),
                    ],
                    className="section-card filter-card",
                ),
                # display the highest-ranking animals for the selected rescue assignment
                html.Section(
                    [
                        html.Div(
                            [
                                html.H2(
                                    "Top Rescue Candidates",
                                    className="section-title",
                                ),
                                html.P(
                                    "The ten highest-scoring eligible animals based on breed and age.",
                                    className="card-subtitle",
                                ),
                            ],
                        ),
                        # populate ranked candidates when a rescue category is selected
                        html.Div(
                            id="ranked-candidates",
                            children=html.P(
                                "Select a rescue category above to view ranked candidates.",
                                className="card-subtitle",
                            ),
                        ),
                    ],
                    className="section-card",
                ),
                html.Div(
                    [
                        html.Section(
                            [
                                html.Div(
                                    [
                                        html.Div(
                                            [
                                                html.H2(
                                                    "Animal Records",
                                                    className="section-title",
                                                ),
                                                html.P(
                                                    "Search columns, sort records, and select an animal.",
                                                    className="card-subtitle",
                                                ),
                                            ],
                                        ),
                                        html.Button(
                                            "Export CSV",
                                            id="export-animals",
                                            n_clicks=0,
                                            className="action-button",
                                        ),
                                        dcc.Download(id="download-animals"),
                                    ],
                                    className="card-heading",
                                ),
                                html.Div(id="record-count", className="record-count"),
                                animal_table(),
                            ],
                            className="section-card records-card",
                        ),
                        # stack selected animal details above the map
                        html.Div(
                            [
                                html.Section(
                                    [
                                        html.H2(
                                            "Animal Profile", className="section-title"
                                        ),
                                        html.P(
                                            "Details for the selected record.",
                                            className="card-subtitle",
                                        ),
                                        html.Div(id="selected-animal-details"),
                                    ],
                                    className="section-card",
                                ),
                                html.Section(
                                    [
                                        html.H2(
                                            "Selected Animal Location",
                                            className="section-title",
                                        ),
                                        html.P(
                                            "Select an animal record to update the map.",
                                            className="card-subtitle",
                                        ),
                                        html.Div(
                                            id="selected-animal-info",
                                            className="selected-animal-info",
                                        ),
                                        html.Div(
                                            id="animal-map",
                                            className="map-container",
                                            style={"minHeight": "0"},
                                        ),
                                        html.Div(
                                            "Location shown is the coordinate recorded in the AAC dataset.",
                                            className="map-caption",
                                        ),
                                    ],
                                    className="section-card location-card",
                                ),
                            ],
                            style={
                                "display": "flex",
                                "flexDirection": "column",
                                "gap": "22px",
                                "minWidth": "0",
                            },
                        ),
                    ],
                    className="primary-grid",
                ),
                # display breed insights beside the rescue candidate summary
                html.A(id="analytics"),
                html.Div(
                    [
                        html.Section(
                            [
                                html.H2("Top 10 Breeds", className="section-title"),
                                html.P(
                                    "Automatically updates with the rescue and table filters.",
                                    className="card-subtitle",
                                ),
                                # reserve space for the breed chart
                                dcc.Graph(
                                    id="breed-chart",
                                    config={
                                        "displayModeBar": False,
                                        "responsive": True,
                                    },
                                    style={"width": "100%", "height": "500px"},
                                ),
                            ],
                            className="section-card",
                        ),
                        html.Section(
                            [
                                html.H2(
                                    "Rescue Candidate Summary",
                                    className="section-title",
                                ),
                                html.P(
                                    "Animals matching the original rescue criteria.",
                                    className="card-subtitle",
                                ),
                                dcc.Graph(
                                    id="overview-rescue-chart",
                                    figure=make_rescue_chart(rescue_counts),
                                    config={"displayModeBar": False},
                                ),
                                html.P(
                                    "Animals may qualify for multiple categories.",
                                    className="chart-note",
                                ),
                            ],
                            className="section-card",
                        ),
                    ],
                    className="insights-grid",
                ),
                # retain staff record creation but don't let the form dominate the dashboard
                html.A(id="staff-tools"),
                html.Section(
                    [
                        html.Details(
                            [
                                html.Summary(
                                    "Add Animal Record", className="staff-summary"
                                ),
                                html.P(
                                    "Staff authentication is enabled for this local dashboard.",
                                    className="card-subtitle",
                                ),
                                html.Div(
                                    [
                                        form_field(
                                            "Animal ID *",
                                            dcc.Input(
                                                id="add-animal-id",
                                                type="text",
                                                placeholder="CS499-TEST-001",
                                            ),
                                        ),
                                        form_field(
                                            "Name",
                                            dcc.Input(
                                                id="add-name",
                                                type="text",
                                                placeholder="Optional",
                                            ),
                                        ),
                                        form_field(
                                            "Animal Type *",
                                            dcc.Dropdown(
                                                id="add-type",
                                                options=[
                                                    {"label": x, "value": x}
                                                    for x in ("Dog", "Cat", "Other")
                                                ],
                                                placeholder="Select type",
                                            ),
                                        ),
                                        form_field(
                                            "Breed *",
                                            dcc.Input(id="add-breed", type="text"),
                                        ),
                                        form_field(
                                            "Sex Upon Outcome *",
                                            dcc.Dropdown(
                                                id="add-sex",
                                                options=[
                                                    {"label": x, "value": x}
                                                    for x in (
                                                        "Intact Male",
                                                        "Intact Female",
                                                        "Neutered Male",
                                                        "Spayed Female",
                                                        "Unknown",
                                                    )
                                                ],
                                                placeholder="Select sex",
                                            ),
                                        ),
                                        form_field(
                                            "Age (Weeks) *",
                                            dcc.Input(
                                                id="add-age",
                                                type="number",
                                                min=0,
                                                step=1,
                                            ),
                                        ),
                                        form_field(
                                            "Latitude",
                                            dcc.Input(
                                                id="add-lat",
                                                type="number",
                                                min=-90,
                                                max=90,
                                                step="any",
                                            ),
                                        ),
                                        form_field(
                                            "Longitude",
                                            dcc.Input(
                                                id="add-long",
                                                type="number",
                                                min=-180,
                                                max=180,
                                                step="any",
                                            ),
                                        ),
                                    ],
                                    className="form-grid",
                                ),
                                html.Button(
                                    "Save Animal Record",
                                    id="save-animal-record",
                                    n_clicks=0,
                                    className="action-button form-submit",
                                ),
                                html.Div(
                                    id="add-record-status",
                                    role="status",
                                    className="form-status",
                                ),
                            ],
                        ),
                        # provide a separate form for updating a selected animal
                        html.Details(
                            [
                                html.Summary(
                                    "Edit Animal Record", className="staff-summary"
                                ),
                                html.P(
                                    "Select an animal in Records to load its information.",
                                    className="card-subtitle",
                                ),
                                html.Div(
                                    [
                                        form_field(
                                            "Animal ID",
                                            dcc.Input(
                                                id="edit-animal-id",
                                                type="text",
                                                readOnly=True,
                                                placeholder="Select an animal",
                                            ),
                                        ),
                                        form_field(
                                            "Name",
                                            dcc.Input(id="edit-name", type="text"),
                                        ),
                                        form_field(
                                            "Animal Type *",
                                            dcc.Dropdown(
                                                id="edit-type",
                                                options=[
                                                    {"label": x, "value": x}
                                                    for x in ("Dog", "Cat", "Other")
                                                ],
                                            ),
                                        ),
                                        form_field(
                                            "Breed *",
                                            dcc.Input(id="edit-breed", type="text"),
                                        ),
                                        form_field(
                                            "Sex Upon Outcome *",
                                            dcc.Dropdown(
                                                id="edit-sex",
                                                options=[
                                                    {"label": x, "value": x}
                                                    for x in (
                                                        "Intact Male",
                                                        "Intact Female",
                                                        "Neutered Male",
                                                        "Spayed Female",
                                                        "Unknown",
                                                    )
                                                ],
                                            ),
                                        ),
                                        form_field(
                                            "Age (Weeks) *",
                                            dcc.Input(
                                                id="edit-age",
                                                type="number",
                                                min=0,
                                                step="any",
                                            ),
                                        ),
                                        form_field(
                                            "Latitude",
                                            dcc.Input(
                                                id="edit-lat",
                                                type="number",
                                                min=-90,
                                                max=90,
                                                step="any",
                                            ),
                                        ),
                                        form_field(
                                            "Longitude",
                                            dcc.Input(
                                                id="edit-long",
                                                type="number",
                                                min=-180,
                                                max=180,
                                                step="any",
                                            ),
                                        ),
                                    ],
                                    className="form-grid",
                                ),
                                html.Button(
                                    "Save Changes",
                                    id="save-animal-changes",
                                    n_clicks=0,
                                    className="action-button form-submit",
                                ),
                                html.Div(
                                    id="edit-record-status",
                                    role="status",
                                    className="form-status",
                                ),
                            ],
                        ),
                    ],
                    className="section-card staff-card",
                ),
                html.Footer(
                    "Grazioso Salvare • CS 499 Software Design & Engineering",
                    className="dashboard-footer",
                ),
            ],
            className="main-content",
        ),
    ],
    className="dashboard-shell",
)


# reload table records when the rescue filter or data changes
# return to the first page when rescue or table filters change
@app.callback(
    Output("animal-table", "page_current"),
    Input("rescue-filter", "value"),
    Input("animal-table", "filter_query"),
    prevent_initial_call=True,
)
def reset_animal_page(filter_type, filter_query):
    return 0


# retrieve only the requested page of animal records from mongodb
@app.callback(
    Output("animal-table", "data"),
    Output("animal-table", "page_count"),
    Output("animal-table", "selected_rows"),
    Input("animal-table", "page_current"),
    Input("animal-table", "page_size"),
    Input("animal-table", "sort_by"),
    Input("animal-table", "filter_query"),
    Input("rescue-filter", "value"),
    Input("record-version", "data"),
)
def update_animal_records(
    page_current, page_size, sort_by, filter_query, filter_type, _version
):
    # retrieve matching animals through the data access layer
    # combine rescue criteria with approved table filters
    query = build_table_query(filter_type, filter_query)

    # count matching records to calculate the number of pages
    total_records = db.count(query)
    page_count = (total_records + page_size - 1) // page_size

    # prevent requests beyond the available pages
    page = min(page_current or 0, max(page_count - 1, 0))

    # use the selected table column and direction for database sorting
    sort_field = "animal_id"
    sort_direction = 1

    if sort_by:
        requested_field = sort_by[0].get("column_id")

        if requested_field in TABLE_FILTER_FIELDS:
            sort_field = requested_field
            sort_direction = -1 if sort_by[0].get("direction") == "desc" else 1

    # retrieve the sorted page directly from mongodb
    records = db.read_page(
        query,
        projection=animal_fields,
        page=page,
        page_size=page_size,
        sort_field=sort_field,
        sort_direction=sort_direction,
    )

    # select the first animal when records are available
    selected_rows = [0] if records else []

    return records, page_count, selected_rows


# update ranked candidates when rescue filters or animal records change
@app.callback(
    Output("ranked-candidates", "children"),
    Input("rescue-filter", "value"),
    Input("record-version", "data"),
)
def update_ranked_candidates(category, _version):
    # require a rescue category before generating recommendations
    if category not in ("water", "mountain", "disaster"):
        return html.P(
            "Select a rescue category above to view ranked candidates.",
            className="card-subtitle",
        )

    # retrieve eligible animals using the existing rescue criteria
    try:
        animals = db.read(rescue_query(category), animal_fields)
        # select the ten strongest candidates with the min-heap
        ranked = rank_candidates(animals, category, k=10)
        # check how many animals are retrieved and ranked
        print(f"Rescue category: {category}")
        print(f"Animals retrieved: {len(animals)}")
        print(f"Candidates ranked: {len(ranked)}")
    except Exception:
        return html.P(
            "Unable to retrieve rescue candidates.",
            className="card-subtitle",
        )

    # display a message when no animals qualify
    if not ranked:
        return html.P(
            "No eligible animals were found for this rescue category.",
            className="card-subtitle",
        )

    # display the ten highest-ranking rescue candidates
    return html.Div(
        [
            html.Div(
                [
                    # display the candidate's rank, name, and animal id
                    html.Div(
                        [
                            html.Strong(f"#{index}"),
                            html.Strong(str(animal.get("name") or "Unnamed Animal")),
                            html.Span(f"ID: {animal.get('animal_id', 'N/A')}"),
                        ],
                        className="candidate-heading",
                    ),
                    # display the candidate's breed, age, and suitability score
                    html.Div(
                        [
                            html.Span(str(animal.get("breed") or "Unknown Breed")),
                            html.Span(
                                f"Age: {animal.get('age_upon_outcome_in_weeks', 0):.1f} weeks"
                            ),
                            html.Strong(f"{result['score']}/10"),
                        ],
                        className="candidate-details",
                    ),
                ],
                className="candidate-card",
            )
            for index, result in enumerate(ranked, start=1)
            for animal in [result["animal"]]
        ],
        className="candidate-grid",
    )


# load the selected animal into the edit form
@app.callback(
    Output("edit-animal-id", "value"),
    Output("edit-name", "value"),
    Output("edit-type", "value"),
    Output("edit-breed", "value"),
    Output("edit-sex", "value"),
    Output("edit-age", "value"),
    Output("edit-lat", "value"),
    Output("edit-long", "value"),
    Input("animal-table", "data"),
    Input("animal-table", "selected_rows"),
)
def load_animal_for_edit(view_data, selected_rows):
    # use the current filtered and sorted table data
    # use the records retrieved for the current table page
    records = view_data or []

    # clear the form when no valid animal is selected
    if not selected_rows or not records:
        return (None,) * 8

    index = selected_rows[0]
    if not isinstance(index, int) or not 0 <= index < len(records):
        return (None,) * 8

    # populate the form without modifying the database
    animal = records[index]
    return (
        animal.get("animal_id"),
        animal.get("name"),
        animal.get("animal_type"),
        animal.get("breed"),
        animal.get("sex_upon_outcome"),
        animal.get("age_upon_outcome_in_weeks"),
        animal.get("location_lat"),
        animal.get("location_long"),
    )


# validate and save changes to the selected animal
@app.callback(
    Output("edit-record-status", "children"),
    Output("record-version", "data", allow_duplicate=True),
    Input("save-animal-changes", "n_clicks"),
    State("edit-animal-id", "value"),
    State("edit-name", "value"),
    State("edit-type", "value"),
    State("edit-breed", "value"),
    State("edit-sex", "value"),
    State("edit-age", "value"),
    State("edit-lat", "value"),
    State("edit-long", "value"),
    State("record-version", "data"),
    prevent_initial_call=True,
)
def save_animal_changes(
    n_clicks,
    animal_id,
    name,
    animal_type,
    breed,
    sex,
    age,
    latitude,
    longitude,
    version,
):
    if not n_clicks:
        raise PreventUpdate

    # require an animal selection before saving
    if not isinstance(animal_id, str) or not animal_id.strip():
        return (
            html.P(
                "Select an animal before saving changes.", style={"color": "#b42318"}
            ),
            version,
        )

    # collect editable fields without changing the animal ID
    changes = {
        "name": name or "",
        "animal_type": animal_type,
        "breed": breed,
        "sex_upon_outcome": sex,
        "age_upon_outcome_in_weeks": age,
    }
    if latitude is not None:
        changes["location_lat"] = latitude
    if longitude is not None:
        changes["location_long"] = longitude

    # validate all submitted fields before updating mongodb
    try:
        changes = validate_animal(changes, updating=True)
    except ValueError as exc:
        return html.P(str(exc), style={"color": "#b42318"}), version

    # update only the record matching the selected animal ID
    try:
        updated = db.update(animal_id.strip(), changes)
    except Exception:
        return (
            html.P(
                "Database error. Changes could not be saved.",
                style={"color": "#b42318"},
            ),
            version,
        )

    if not updated:
        return html.P("Animal record not found.", style={"color": "#b42318"}), version

    # refresh the table and charts after a successful update
    return (
        html.P(
            f"Animal {animal_id.strip()} updated successfully.",
            style={"color": "#0d766c"},
        ),
        (version or 0) + 1,
    )


# create records through the service validation and CRUD data-access layers
@app.callback(
    Output("add-record-status", "children"),
    Output("record-version", "data"),
    Input("save-animal-record", "n_clicks"),
    State("add-animal-id", "value"),
    State("add-name", "value"),
    State("add-type", "value"),
    State("add-breed", "value"),
    State("add-sex", "value"),
    State("add-age", "value"),
    State("add-lat", "value"),
    State("add-long", "value"),
    State("record-version", "data"),
    prevent_initial_call=True,
)
def create_animal_record(
    n_clicks,
    animal_id,
    name,
    animal_type,
    breed,
    sex,
    age,
    latitude,
    longitude,
    version,
):
    if not n_clicks:
        raise PreventUpdate

    # separate validation of values from the database write
    record = {
        "animal_id": animal_id,
        "name": name or "",
        "animal_type": animal_type,
        "breed": breed,
        "sex_upon_outcome": sex,
        "age_upon_outcome_in_weeks": age,
    }
    if latitude is not None:
        record["location_lat"] = latitude
    if longitude is not None:
        record["location_long"] = longitude

    try:
        record = validate_animal(record)
    except ValueError as exc:
        return html.P(str(exc), style={"color": "#b42318"}), version

    # prevent duplicate animal IDs
    try:
        if db.exists({"animal_id": record["animal_id"]}):

            return (
                html.P("That Animal ID already exists.", style={"color": "#b42318"}),
                version,
            )
        created = db.create(record)
    except Exception:
        return (
            html.P(
                "Database error. The animal record could not be saved.",
                style={"color": "#b42318"},
            ),
            version,
        )

    if not created:
        return (
            html.P("Unable to save the animal record.", style={"color": "#b42318"}),
            version,
        )

    return (
        html.P(
            f"Animal {record['animal_id']} saved successfully.",
            style={"color": "#0d766c", "fontWeight": "600"},
        ),
        (version or 0) + 1,
    )


# refresh overview totals and charts after a new record is saved
@app.callback(
    Output("stats-total", "children"),
    Output("stats-dogs", "children"),
    Output("stats-cats", "children"),
    Output("overview-type-chart", "figure"),
    Output("overview-rescue-chart", "figure"),
    Input("record-version", "data"),
)
def refresh_overview(_version):
    # retrieve updated animal type totals using MongoDB aggregation
    type_counts = db.aggregate_field_counts("animal_type")

    # count animals eligible for each rescue category
    counts = {
        category: db.count(rescue_query(category))
        for category in ("water", "mountain", "disaster")
    }

    # update dashboard statistics and charts
    return (
        f"{db.count({}):,}",
        f"{db.count({'animal_type': 'Dog'}):,}",
        f"{db.count({'animal_type': 'Cat'}):,}",
        make_overview_chart(type_counts),
        make_rescue_chart(counts),
    )


# show the number of records currently in the table
# count all matching animals independently of the current table page
@app.callback(
    Output("record-count", "children"),
    Output("stats-matching", "children"),
    Input("rescue-filter", "value"),
    Input("animal-table", "filter_query"),
    Input("record-version", "data"),
)
def update_record_count(filter_type, filter_query, _version):

    # apply the same database filters used by the animal table
    query = build_table_query(filter_type, filter_query)

    # count matching records without retrieving the documents
    count = db.count(query)

    return f"{count:,} matching records", f"{count:,}"


# display the selected record without requiring another database request
def detail_item(label, value):
    return html.Div(
        [
            html.Div(
                label,
                style={"fontSize": "12px", "color": "#748397", "marginBottom": "5px"},
            ),
            html.Div(
                str(value) if value is not None and value != "" else "Not recorded",
                style={
                    "fontSize": "15px",
                    "fontWeight": "600",
                    "overflowWrap": "anywhere",
                },
            ),
        ]
    )


# display details for the selected animal without another query
@app.callback(
    Output("selected-animal-details", "children"),
    Input("animal-table", "data"),
    Input("animal-table", "selected_rows"),
)
def show_selected_animal(view_data, selected_rows):
    # retrieve the selected animal from the current page
    records = view_data or []
    if not records:
        return html.P(
            "No animals match the current filters.", className="page-subtitle"
        )

    row_index = (
        selected_rows[0]
        if selected_rows and 0 <= selected_rows[0] < len(records)
        else 0
    )
    animal = records[row_index]
    return html.Div(
        [
            detail_item("Animal ID", animal.get("animal_id")),
            detail_item("Name", animal.get("name")),
            detail_item("Animal Type", animal.get("animal_type")),
            detail_item("Breed", animal.get("breed")),
            detail_item("Sex Upon Outcome", animal.get("sex_upon_outcome")),
            detail_item("Age (Weeks)", animal.get("age_upon_outcome_in_weeks")),
        ],
        style={
            "display": "grid",
            "gridTemplateColumns": "repeat(auto-fit, minmax(160px, 1fr))",
            "gap": "20px",
        },
    )


# export all matching rows after rescue filters and table filters, not just the current page
# export all matching database records regardless of the current table page
@app.callback(
    Output("download-animals", "data"),
    Input("export-animals", "n_clicks"),
    State("rescue-filter", "value"),
    State("animal-table", "filter_query"),
    prevent_initial_call=True,
)
def export_filtered_records(n_clicks, filter_type, filter_query):
    if not n_clicks:
        raise PreventUpdate

    # apply the same rescue and column filters used by the table
    query = build_table_query(filter_type, filter_query)

    # retrieve all records when no filtered data is available
    # retrieve every matching record rather than the current page
    records = db.read(query, animal_fields)

    if not records:
        raise PreventUpdate

    buffer = io.StringIO(newline="")
    writer = csv.writer(buffer)
    writer.writerow([heading for heading, _ in export_columns])

    for animal in records:
        row = []
        for _, key in export_columns:
            value = animal.get(key)
            # prevent spreadsheet applications from interpreting untrusted text as formulas
            if isinstance(value, str) and value.lstrip().startswith(
                ("=", "+", "-", "@")
            ):
                value = "'" + value
            row.append("" if value is None else value)
        writer.writerow(row)

    return {
        "content": buffer.getvalue(),
        "filename": "grazioso_salvare_animals.csv",
        "type": "text/csv",
    }


# rebuild the breed chart from the filtered records
# rebuild the breed chart from all matching database records
@app.callback(
    Output("breed-chart", "figure"),
    Input("rescue-filter", "value"),
    Input("animal-table", "filter_query"),
    Input("record-version", "data"),
)
def update_breed_chart(filter_type, filter_query, _version):

    # apply the same filters used by the paginated animal table
    query = build_table_query(filter_type, filter_query)

    # retrieve the ten most common breeds directly from MongoDB
    breed_counts = db.aggregate_field_counts("breed", query, limit=10)

    # prepare the aggregated breed counts for the chart
    top_breeds = [(str(item["_id"]), item["count"]) for item in breed_counts]
    fig = go.Figure()
    if top_breeds:
        breeds, values = zip(*top_breeds)
        fig.add_trace(
            go.Bar(
                x=list(breeds),
                y=list(values),
                marker_color="#0d9488",
                text=list(values),
                textposition="outside",
                hovertemplate="<b>%{x}</b><br>Animals: %{y}<extra></extra>",
            )
        )
    else:
        fig.add_annotation(
            text="No animals match the selected filters.",
            x=0.5,
            y=0.5,
            xref="paper",
            yref="paper",
            showarrow=False,
            font={"size": 16, "color": "#748397"},
        )
    fig.update_layout(
        template="plotly_white",
        height=420,
        margin={"l": 35, "r": 30, "t": 35, "b": 100},
        font={"family": "DM Sans, sans-serif", "color": "#243447"},
        plot_bgcolor="white",
        paper_bgcolor="white",
        showlegend=False,
        xaxis={"title": "", "tickangle": -30, "automargin": True, "showgrid": False},
        yaxis={
            "title": "Number of Animals",
            "rangemode": "tozero",
            "gridcolor": "#edf1f5",
        },
    )
    return fig


# plot valid animal coordinates and highlight the selected record
@app.callback(
    Output("animal-map", "children"),
    Output("selected-animal-info", "children"),
    Input("animal-table", "data"),
    Input("animal-table", "selected_rows"),
)
def update_animal_map(view_data, selected_rows):
    # use the selected animal from the current table page
    view_data = view_data or []
    if not view_data:
        return html.P("No animal records available."), ""

    index = (
        selected_rows[0]
        if selected_rows and 0 <= selected_rows[0] < len(view_data)
        else 0
    )
    animal = view_data[index]
    name = animal.get("name") or "Unnamed Animal"
    breed = animal.get("breed") or "Unknown Breed"
    animal_id = animal.get("animal_id") or "Not Available"
    details = html.Div(
        [
            html.Strong(str(name)),
            html.Span(f" | {breed} | ID: {animal_id}", style={"color": "#748397"}),
        ],
        style={"fontSize": "14px"},
    )
    # validate coordinates before creating a map component
    try:
        latitude = float(animal.get("location_lat"))
        longitude = float(animal.get("location_long"))
        if not (
            isfinite(latitude)
            and isfinite(longitude)
            and -90 <= latitude <= 90
            and -180 <= longitude <= 180
        ):
            raise ValueError("Invalid coordinates")
    except (TypeError, ValueError):
        return html.P("No valid location coordinates are available."), details

    map_component = dl.Map(
        center=[latitude, longitude],
        zoom=12,
        style={"width": "100%", "height": "320px", "borderRadius": "10px"},
        children=[
            dl.TileLayer(),
            dl.Marker(
                position=[latitude, longitude],
                children=[
                    dl.Tooltip(str(name)),
                    dl.Popup(
                        [
                            html.H4(str(name)),
                            html.P(f"Animal ID: {animal_id}"),
                            html.P(f"Breed: {breed}"),
                            html.P(f"Coordinates: {latitude:.5f}, {longitude:.5f}"),
                        ]
                    ),
                ],
            ),
        ],
    )
    return map_component, details


if __name__ == "__main__":
    app.run(port=8052)
