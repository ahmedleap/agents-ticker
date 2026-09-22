-- Sample data for instruments table
-- Run this AFTER schema.sql to populate test data

-- Insert popular stocks with initial prices
-- The price_updated_at and actual bid/ask will be updated by the ticker service every 10 seconds

INSERT INTO instruments (instrument_id, ticker, name, asset_class, industry, bid, ask, price_updated_at)
VALUES
    ('550e8400-e29b-41d4-a716-446655440001'::uuid, 'AAPL', 'Apple Inc.', 'STOCK', 'Technology', 150.00, 150.25, CURRENT_TIMESTAMP),
    ('550e8400-e29b-41d4-a716-446655440002'::uuid, 'MSFT', 'Microsoft Corporation', 'STOCK', 'Technology', 370.00, 370.50, CURRENT_TIMESTAMP),
    ('550e8400-e29b-41d4-a716-446655440003'::uuid, 'GOOGL', 'Alphabet Inc.', 'STOCK', 'Technology', 138.00, 138.50, CURRENT_TIMESTAMP),
    ('550e8400-e29b-41d4-a716-446655440004'::uuid, 'AMZN', 'Amazon.com Inc.', 'STOCK', 'Technology', 175.00, 175.50, CURRENT_TIMESTAMP),
    ('550e8400-e29b-41d4-a716-446655440005'::uuid, 'NVDA', 'NVIDIA Corporation', 'STOCK', 'Technology', 120.00, 120.75, CURRENT_TIMESTAMP),
    ('550e8400-e29b-41d4-a716-446655440006'::uuid, 'TSLA', 'Tesla Inc.', 'STOCK', 'Automotive', 250.00, 251.00, CURRENT_TIMESTAMP),
    ('550e8400-e29b-41d4-a716-446655440007'::uuid, 'META', 'Meta Platforms Inc.', 'STOCK', 'Technology', 310.00, 310.75, CURRENT_TIMESTAMP),
    ('550e8400-e29b-41d4-a716-446655440008'::uuid, 'SPY', 'SPDR S&P 500 ETF Trust', 'ETF', 'Broad Market', 480.00, 480.50, CURRENT_TIMESTAMP),
    ('550e8400-e29b-41d4-a716-446655440009'::uuid, 'QQQ', 'Invesco QQQ Trust', 'ETF', 'Technology', 380.00, 380.75, CURRENT_TIMESTAMP),
    ('550e8400-e29b-41d4-a716-446655440010'::uuid, 'IWM', 'iShares Russell 2000 ETF', 'ETF', 'Small Cap', 200.00, 200.50, CURRENT_TIMESTAMP);

-- Verify insertion
SELECT 
    ticker, 
    name, 
    asset_class, 
    bid, 
    ask, 
    mid_price,
    price_updated_at
FROM instruments
ORDER BY ticker;
