/**
 * WebMCP Standard Client-Side Bridge (W3C / Anthropic Web Model Context Protocol).
 * Exposes typed in-browser DOM and client tools to AI agents and web assistants.
 */

class WebMCPBridge {
    constructor(appName, tools = {}) {
        this.appName = appName;
        this.tools = tools;
        this.isRegistered = false;
        this.init();
    }

    init() {
        if (!window.webMCP) {
            window.webMCP = {
                version: "1.0.0",
                registeredSurfaces: {},
                executeTool: async (surfaceName, toolName, args) => {
                    const surface = window.webMCP.registeredSurfaces[surfaceName];
                    if (!surface) throw new Error(`Surface '${surfaceName}' not found`);
                    const tool = surface.tools[toolName];
                    if (!tool) throw new Error(`Tool '${toolName}' not found on surface '${surfaceName}'`);
                    return await tool.handler(args);
                }
            };
        }

        window.webMCP.registeredSurfaces[this.appName] = {
            appName: this.appName,
            tools: this.tools,
            getSchema: () => Object.entries(this.tools).map(([name, def]) => ({
                name,
                description: def.description,
                parameters: def.parameters
            }))
        };

        this.isRegistered = true;
        console.log(`[WebMCP] Registered '${this.appName}' with ${Object.keys(this.tools).length} typed client tools.`);
    }

    registerTool(name, description, parameters, handler) {
        this.tools[name] = { description, parameters, handler };
        if (window.webMCP && window.webMCP.registeredSurfaces[this.appName]) {
            window.webMCP.registeredSurfaces[this.appName].tools[name] = this.tools[name];
        }
    }
}

window.WebMCPBridge = WebMCPBridge;
