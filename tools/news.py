from ddgs import DDGS
class News:
    @staticmethod
    def get_news(news_topic:str):
        try:
            results=DDGS().news(
                news_topic,
                region="in-en",
                max_results=5
            )
        except Exception as e:
            return {"error": str(e)}

        return results

