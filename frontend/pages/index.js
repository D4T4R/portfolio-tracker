import { useState, useEffect } from 'react'
import {
  Box,
  Container,
  Heading,
  SimpleGrid,
  Spinner,
  Alert,
  AlertIcon,
  AlertTitle,
  AlertDescription,
  Button,
  Flex,
  Text,
  useToast,
  VStack,
  HStack,
  useColorModeValue
} from '@chakra-ui/react'
import { keyframes } from '@emotion/react'
import Link from 'next/link'
import axios from 'axios'
import { motion, AnimatePresence } from 'framer-motion'
import StockCard from '../components/StockCard'
import Portfolio from '../components/Portfolio'
import Navigation from '../components/Navigation'
import { NotificationProvider, useNotifications } from '../contexts/NotificationContext'

const MotionBox = motion(Box)
const MotionSimpleGrid = motion(SimpleGrid)
const MotionContainer = motion(Container)

// Animated gradient keyframes
const gradientShift = keyframes`
  0% { background-position: 0% 50%; }
  50% { background-position: 100% 50%; }
  100% { background-position: 0% 50%; }
`

function HomeContent() {
  const [stockData, setStockData] = useState(null)
  const [portfolioData, setPortfolioData] = useState(null)
  const [loading, setLoading] = useState(true)
  const [lastUpdated, setLastUpdated] = useState(null)
  const [error, setError] = useState(null)
  const toast = useToast()
  const { updatePrices } = useNotifications()

  const fetchStockData = async () => {
    try {
      setLoading(true)
      setError(null)
      
      // Fetch both stock prices and portfolio data
      const [pricesResponse, portfolioResponse] = await Promise.all([
        axios.get('http://localhost:5000/api/prices'),
        axios.get('http://localhost:5000/api/portfolio-with-live-prices')
      ])
      
      setStockData(pricesResponse.data)
      setPortfolioData(portfolioResponse.data)
      setLastUpdated(new Date())
      
      // Update notification system with new prices
      updatePrices(pricesResponse.data, portfolioResponse.data)
      
      if (lastUpdated) {
        toast({
          title: 'Data Updated',
          description: 'Stock prices and portfolio have been refreshed',
          status: 'success',
          duration: 2000,
          isClosable: true,
        })
      }
    } catch (err) {
      setError('Failed to fetch data. Make sure the Flask backend is running on port 5000.')
      console.error('Error fetching data:', err)
      toast({
        title: 'Error',
        description: 'Failed to fetch data',
        status: 'error',
        duration: 5000,
        isClosable: true,
      })
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    fetchStockData()
    // Auto-refresh every 90 seconds
    const interval = setInterval(fetchStockData, 90000)
    return () => clearInterval(interval)
  }, [])

  if (loading && !stockData) {
    return (
      <Box minH="100vh" bg="gray.950">
        <Navigation />
        <Container maxW="container.xl" py={8}>
          <VStack spacing={8}>
            <Heading size="2xl" color="white" textAlign="center">
              Portfolio Tracker
            </Heading>
            <Spinner size="xl" color="blue.400" thickness="4px" />
            <Text color="gray.400" fontSize="lg">Loading stock data...</Text>
          </VStack>
        </Container>
      </Box>
    )
  }

  if (error) {
    return (
      <Box minH="100vh" bg="gray.900">
        <Navigation />
        <Container maxW="container.xl" py={8}>
          <VStack spacing={6}>
            <Heading size="2xl" color="white" textAlign="center">
              Portfolio Tracker
            </Heading>
            <Alert status="error" borderRadius="lg" maxW="md">
              <AlertIcon />
              <Box>
                <AlertTitle>Connection Error!</AlertTitle>
                <AlertDescription>{error}</AlertDescription>
              </Box>
            </Alert>
            <Button
              onClick={fetchStockData}
              colorScheme="blue"
              isLoading={loading}
              loadingText="Retrying..."
            >
              Retry
            </Button>
          </VStack>
        </Container>
      </Box>
    )
  }

  return (
    <Box minH="100vh" bg="gray.950">
      <Navigation />
      <Container maxW="container.xl" py={6}>
        <VStack spacing={6}>
          {/* Header */}
          <MotionBox
            as={Flex}
            w="full" 
            justify="space-between" 
            align="center" 
            flexWrap="wrap" 
            gap={4}
            initial={{ y: -20, opacity: 0 }}
            animate={{ y: 0, opacity: 1 }}
            transition={{ duration: 0.6, delay: 0.4 }}
          >
            <VStack align="start" spacing={1}>
              <Heading size="2xl" color="white" textShadow="2px 2px 4px rgba(0,0,0,0.4)">
                Live Portfolio Tracker
              </Heading>
              <Text color="whiteAlpha.800" fontSize="sm" textShadow="1px 1px 2px rgba(0,0,0,0.3)">
                Real-time stock prices
                {lastUpdated && ` - Updated: ${lastUpdated.toLocaleTimeString()}`}
              </Text>
            </VStack>
            
            <HStack spacing={3}>
              <Link href="/portfolio" legacyBehavior passHref>
                <Button 
                  as="a"
                  bg="whiteAlpha.200"
                  color="white"
                  backdropFilter="blur(10px)"
                  border="1px solid"
                  borderColor="whiteAlpha.300"
                  _hover={{
                    bg: 'whiteAlpha.300',
                    transform: 'translateY(-2px)',
                    boxShadow: '0 8px 25px rgba(0,0,0,0.2)'
                  }}
                  transition="all 0.3s ease"
                >
                  Portfolio Table
                </Button>
              </Link>
              <Button
                onClick={fetchStockData}
                bg="whiteAlpha.200"
                color="white"
                backdropFilter="blur(10px)"
                border="1px solid"
                borderColor="whiteAlpha.300"
                isLoading={loading}
                loadingText="Refreshing..."
                _hover={{
                  bg: 'whiteAlpha.300',
                  transform: 'translateY(-2px)',
                  boxShadow: '0 8px 25px rgba(0,0,0,0.2)'
                }}
                transition="all 0.3s ease"
              >
                Refresh
              </Button>
            </HStack>
          </MotionBox>

          {/* Main Content */}
          {stockData && (
            <AnimatePresence>
              {/* Enhanced Portfolio Overview */}
              {portfolioData && (
                <MotionBox
                  initial={{ opacity: 0, y: 20 }}
                  animate={{ opacity: 1, y: 0 }}
                  transition={{ duration: 0.6, delay: 0.6 }}
                  w="full"
                >
                  <Portfolio 
                    stockData={stockData} 
                    portfolioSummary={portfolioData.summary}
                  />
                </MotionBox>
              )}
              
              {/* Stock Cards with Portfolio Integration */}
              <MotionSimpleGrid 
                columns={{ base: 1, md: 2, lg: 3, xl: 4 }} 
                spacing={6} 
                w="full"
                initial={{ opacity: 0, scale: 0.9 }}
                animate={{ opacity: 1, scale: 1 }}
                transition={{ duration: 0.8, delay: 0.8 }}
              >
                {Object.entries(stockData.prices).map(([name, data], index) => {
                  // Find corresponding portfolio data for this stock
                  const stockPortfolioData = portfolioData?.portfolioData?.find(
                    stock => stock.stockName === name && stock.quantity > 0
                  )
                  
                  return (
                    <MotionBox
                      key={name}
                      initial={{ opacity: 0, y: 30, scale: 0.8 }}
                      animate={{ opacity: 1, y: 0, scale: 1 }}
                      transition={{ duration: 0.5, delay: 1 + index * 0.1 }}
                      whileHover={{ y: -5, transition: { duration: 0.2 } }}
                    >
                      <StockCard 
                        name={name} 
                        data={data}
                        portfolioData={stockPortfolioData} // Pass portfolio data if available
                        totalPortfolioValue={portfolioData?.summary?.totalCurrentValue} // Pass total portfolio value
                      />
                    </MotionBox>
                  )
                })}
              </MotionSimpleGrid>
              
              {/* Portfolio-Only Stocks (not in live prices) */}
              {portfolioData && (
                <>
                  {portfolioData.portfolioData
                    .filter(stock => 
                      stock.quantity > 0 && 
                      !Object.keys(stockData.prices).includes(stock.stockName)
                    ).length > 0 && (
                    <MotionBox
                      as={VStack}
                      spacing={4} 
                      w="full" 
                      mt={8}
                      initial={{ opacity: 0, y: 40 }}
                      animate={{ opacity: 1, y: 0 }}
                      transition={{ duration: 0.6, delay: 1.5 }}
                    >
                      <Heading size="lg" color="white" textAlign="center" textShadow="2px 2px 4px rgba(0,0,0,0.4)">
                        Other Portfolio Holdings
                      </Heading>
                      <Text color="whiteAlpha.700" fontSize="sm" textAlign="center" textShadow="1px 1px 2px rgba(0,0,0,0.3)">
                        Holdings not available in live price feed
                      </Text>
                      <MotionSimpleGrid 
                        columns={{ base: 1, md: 2, lg: 3, xl: 4 }} 
                        spacing={6} 
                        w="full"
                        initial={{ opacity: 0 }}
                        animate={{ opacity: 1 }}
                        transition={{ duration: 0.6, delay: 1.7 }}
                      >
                        {portfolioData.portfolioData
                          .filter(stock => 
                            stock.quantity > 0 && 
                            !Object.keys(stockData.prices).includes(stock.stockName)
                          )
                          .map((stock, index) => (
                            <MotionBox
                              key={stock.stockName}
                              initial={{ opacity: 0, y: 30, scale: 0.8 }}
                              animate={{ opacity: 1, y: 0, scale: 1 }}
                              transition={{ duration: 0.5, delay: 1.9 + index * 0.1 }}
                              whileHover={{ y: -5, transition: { duration: 0.2 } }}
                            >
                              <StockCard 
                                name={stock.stockName}
                                data={{
                                  price: stock.currentPrice,
                                  change: 0,
                                  changePercent: 0,
                                  symbol: stock.symbol
                                }}
                                portfolioData={stock}
                                totalPortfolioValue={portfolioData?.summary?.totalCurrentValue}
                              />
                            </MotionBox>
                          ))
                        }
                      </MotionSimpleGrid>
                    </MotionBox>
                  )}
                </>
              )}
            </AnimatePresence>
          )}
        </VStack>
      </Container>
    </Box>
  )
}

export default function Home() {
  return (
    <NotificationProvider>
      <HomeContent />
    </NotificationProvider>
  )
}
