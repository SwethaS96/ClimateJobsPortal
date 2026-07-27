from scraper.site_config import SiteConfigLoader

loader = SiteConfigLoader()

sites = loader.load_enabled_websites()

print(f"Loaded {len(sites)} websites")

for site in sites:
    print("-------------------")
    print(site.id)
    print(site.page_name)
    print(site.url)
    print(site.parser_name)