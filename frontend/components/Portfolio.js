import { useState, useEffect } from 'react'
import {
  Box,
  SimpleGrid,
  Stat,
  StatLabel,
  StatNumber,
  Heading,
  Text,
  VStack
} from '@chakra-ui/react'

export default function Portfolio({ stockData, portfolioSummary }) {
  const [portfolioStats, setPortfolioStats] = useState(null)

  useEffect(() => {
    if (portfolioSummary) {
      // Use actual portfolio summary data
      setPortfolioStats({
        totalStocks: portfolioSummary.totalStocks || 0,
        gainers: portfolioSummary.gainers || 0,
        losers: portfolioSummary.losers || 0,
        totalInvestedValue: portfolioSummary.totalInvestedValue || 0,
        totalCurrentValue: portfolioSummary.totalCurrentValue || 0,
        totalPnL: portfolioSummary.totalPnL || 0,
        totalPnLPercent: portfolioSummary.totalPnLPercent || 0
      })
    } else if (stockData && stockData.prices) {
      // Fallback to stock data analysis
      const prices = Object.values(stockData.prices)
      const totalStocks = prices.length
      const gainers = prices.filter(stock => stock.change > 0).length
      const losers = prices.filter(stock => stock.change < 0).length
      const unchanged = prices.filter(stock => stock.change === 0).length
      
      const avgChange = prices.reduce((sum, stock) => sum + stock.change, 0) / totalStocks
      const totalChangePercent = prices.reduce((sum, stock) => sum + stock.changePercent, 0) / totalStocks

      setPortfolioStats({
        totalStocks,
        gainers,
        losers,
        unchanged,
        avgChange: avgChange.toFixed(2),
        totalChangePercent: totalChangePercent.toFixed(2)
      })
    }
  }, [stockData, portfolioSummary])

  if (!portfolioStats) return null

  const isPortfolioPositive = portfolioStats.totalPnL ? portfolioStats.totalPnL >= 0 : portfolioStats.avgChange >= 0
  const hasPortfolioData = portfolioSummary !== undefined

  return (
    <Box
      bg="gray.800"
      border="1px solid"
      borderColor="gray.700"
      borderRadius="xl"
      p={6}
      boxShadow="lg"
      w="full"
      mb={6}
    >
      <VStack spacing={6} align="stretch">
        <Heading size="lg" color="white" textAlign="center">
          {hasPortfolioData ? 'Portfolio Overview' : 'Market Overview'}
        </Heading>
        
        {/* Main Stats Grid */}
        <SimpleGrid columns={{ base: 2, md: hasPortfolioData ? 6 : 4 }} spacing={4}>
          <Stat textAlign="center">
            <StatLabel color="gray.400">Total Stocks</StatLabel>
            <StatNumber color="white" fontSize="2xl">
              {portfolioStats.totalStocks}
            </StatNumber>
          </Stat>
          
          <Stat textAlign="center">
            <StatLabel color="gray.400">Gainers</StatLabel>
            <StatNumber color="green.400" fontSize="2xl">
              {portfolioStats.gainers}
            </StatNumber>
          </Stat>
          
          <Stat textAlign="center">
            <StatLabel color="gray.400">Losers</StatLabel>
            <StatNumber color="red.400" fontSize="2xl">
              {portfolioStats.losers}
            </StatNumber>
          </Stat>
          
          {!hasPortfolioData && (
            <Stat textAlign="center">
              <StatLabel color="gray.400">Unchanged</StatLabel>
              <StatNumber color="gray.400" fontSize="2xl">
                {portfolioStats.unchanged}
              </StatNumber>
            </Stat>
          )}
          
          {/* Portfolio-specific stats */}
          {hasPortfolioData && (
            <>
              <Stat textAlign="center">
                <StatLabel color="gray.400">Invested</StatLabel>
                <StatNumber color="blue.400" fontSize={["lg", "xl"]}>
                  ₹{portfolioStats.totalInvestedValue?.toLocaleString()}
                </StatNumber>
              </Stat>
              
              <Stat textAlign="center">
                <StatLabel color="gray.400">Current</StatLabel>
                <StatNumber color="purple.400" fontSize={["lg", "xl"]}>
                  ₹{portfolioStats.totalCurrentValue?.toLocaleString()}
                </StatNumber>
              </Stat>
              
              <Stat textAlign="center">
                <StatLabel color="gray.400">P&L</StatLabel>
                <StatNumber color={isPortfolioPositive ? 'green.400' : 'red.400'} fontSize={["lg", "xl"]}>
                  {isPortfolioPositive ? '+' : ''}₹{portfolioStats.totalPnL?.toLocaleString()}
                </StatNumber>
              </Stat>
            </>
          )}
        </SimpleGrid>
        
        {/* Performance Summary */}
        <Box
          bg={isPortfolioPositive ? 'green.900' : 'red.900'}
          border="1px solid"
          borderColor={isPortfolioPositive ? 'green.600' : 'red.600'}
          borderRadius="lg"
          p={4}
          textAlign="center"
        >
          <Text 
            color={isPortfolioPositive ? 'green.400' : 'red.400'}
            fontSize="lg"
            fontWeight="bold"
          >
            {hasPortfolioData ? (
              `Overall P&L: ${isPortfolioPositive ? '+' : ''}₹${portfolioStats.totalPnL?.toLocaleString()} (${isPortfolioPositive ? '+' : ''}${portfolioStats.totalPnLPercent}%)`
            ) : (
              `Avg Change: ${isPortfolioPositive ? '+' : ''}₹${portfolioStats.avgChange} (${isPortfolioPositive ? '+' : ''}${portfolioStats.totalChangePercent}%)`
            )}
          </Text>
        </Box>
        
        <Text color="gray.500" fontSize="sm" textAlign="center" fontStyle="italic">
          {hasPortfolioData ? 
            'Portfolio data updated with live prices' : 
            `Last updated: ${stockData?.date} at ${stockData ? new Date(stockData.timestamp).toLocaleTimeString() : ''}`
          }
        </Text>
      </VStack>
    </Box>
  )
}
