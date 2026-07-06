import os

def build():
    src_dir = "src"
    
    # Read core
    core_path = os.path.join(src_dir, "core.py")
    with open(core_path, "r", encoding="utf-8") as f:
        core_content = f.read()
        
    # Build bot.py
    bot_template_path = os.path.join(src_dir, "bot_template.py")
    with open(bot_template_path, "r", encoding="utf-8") as f:
        bot_template_content = f.read()
        
    bot_content = bot_template_content.replace("# === DOWNLOADER_CORE ===", core_content)
    with open("bot.py", "w", encoding="utf-8") as f:
        f.write(bot_content)
    print("Built bot.py")
        
    # Build module.py
    module_template_path = os.path.join(src_dir, "module_template.py")
    with open(module_template_path, "r", encoding="utf-8") as f:
        module_template_content = f.read()
        
    module_content = module_template_content.replace("# === DOWNLOADER_CORE ===", core_content)
    os.makedirs("module", exist_ok=True)
    with open(os.path.join("module", "module.py"), "w", encoding="utf-8") as f:
        f.write(module_content)
    print("Built module/module.py")

if __name__ == "__main__":
    build()
