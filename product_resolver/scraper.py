from modules.scraper.scraper_firecrawl import scrape_and_extract_info


class ProductScraper:

    def scrape(self, url: str) -> str:
        """
        Scrape the page at url using firecrawl.
        Returns the page content as a markdown string.
        Raises ValueError if the page cannot be scraped or returns empty content.
        """
        result = scrape_and_extract_info(url)
        if not result:
            raise ValueError(f"Failed to scrape content from {url}")
        return result
