def run_plugin(source_code, context):
    exec(source_code, context)
    return context.get("result")
