import unittest
from unittest.mock import MagicMock, patch

class TestCamperisScraper(unittest.TestCase):

    @patch('requests.Session.post')
    @patch('requests.Session.get')
    @patch('scraper_utils.process_listing')
    def test_run_scraper_execution(self, mock_process_listing, mock_get, mock_post):
        from scraper_camperis import run_scraper

        # 1. Mock Pagina Iniziale Elenco
        html_usato_index = """
        <html>
            <body>
                <a href="https://www.camperis.com/laika-ecovip-712-00055128/">LAIKA ECOVIP 712</a>
                <a href="https://www.camperis.com/noleggio/">Noleggio</a>
            </body>
        </html>
        """

        # 2. Mock Pagina Dettaglio Veicolo
        html_dettaglio = """
        <html>
            <head>
                <meta property="og:image" content="https://www.camperis.com/uploads/laika.jpg" />
            </head>
            <body>
                <h1>LAIKA ECOVIP 712</h1>
                <p>Prezzo: 74.900 €</p>
                <p>Anno: 2018 - Km: 32.000</p>
            </body>
        </html>
        """

        def mock_get_router(url, **kwargs):
            response = MagicMock()
            response.status_code = 200
            if "laika-ecovip-712-00055128" in url:
                response.text = html_dettaglio
            else:
                response.text = html_usato_index
            return response

        mock_get.side_effect = mock_get_router
        
        # Mock della chiamata POST AJAX per interrompere le iterazioni successive
        mock_post_resp = MagicMock()
        mock_post_resp.status_code = 200
        mock_post_resp.json.return_value = {"template": ""}
        mock_post.return_value = mock_post_resp

        # Esecuzione
        db_mock = MagicMock()
        config_mock = {}
        run_scraper(db_mock, config_mock)

        # Asserzioni
        self.assertTrue(mock_process_listing.called)
        args = mock_process_listing.call_args[0]
        
        self.assertEqual(args[2], "https://www.camperis.com/laika-ecovip-712-00055128/")
        self.assertEqual(args[3], "Camperis")
        self.assertEqual(args[5], 74900)
        self.assertEqual(args[7], "https://www.camperis.com/uploads/laika.jpg")
        self.assertIn("Condizione: Usato", args[4])

if __name__ == '__main__':
    unittest.main()