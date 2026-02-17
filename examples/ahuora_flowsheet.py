import os
import json
import io
from ahuora_builder.flowsheet_manager import FlowsheetManager
from ahuora_builder_types.flowsheet_schema import FlowsheetSchema
from idaes.core.util.model_diagnostics import DiagnosticsToolbox
from idaes_mcp.server import start_mcp_server
from harden_flowsheet import harden_model
from ahuora_builder.methods.property_map_manipulation import update_property


INPUT_FILE = "json/model.json"

# Get current location (so that we can retrieve pump.json)
__location__ = os.path.realpath(os.path.join(os.getcwd(), os.path.dirname(__file__)))


with open(os.path.join(__location__, INPUT_FILE), 'r') as file:

    data = json.load(file)

    flowsheet_schema = FlowsheetSchema.model_validate(data)
    flowsheet = FlowsheetManager(flowsheet_schema)
    flowsheet.load()
    flowsheet.initialise()
    assert flowsheet.degrees_of_freedom() == 0, "Degrees of freedom is not 0: " + str(flowsheet.degrees_of_freedom())
    flowsheet.report_statistics()
    try:
        flowsheet.solve()
    except Exception as e:
        print(e)
    flowsheet.diagnose_problems()

    flowsheet.properties_map.items()

    
    
    
    m = flowsheet.model
    harden_model(m)
    dt = DiagnosticsToolbox(m)

    dt.display_constraints_with_large_residuals()

    print("Starting MCP server at http://127.0.0.1:8005/mcp")
    start_mcp_server(m, host="127.0.0.1", port=8005, allow_remote_hosts=True)