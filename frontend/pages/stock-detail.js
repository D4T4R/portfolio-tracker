import { useState, useEffect } from 'react'
import { useRouter } from 'next/router'
import {
  Box,
  Container,
  Heading,
  VStack,
  HStack,
  Card,
  CardBody,
  Stat,
  StatLabel,
  StatNumber,
  StatHelpText,
  Badge,
  Divider,
  Button,
  Flex,
  Text,
  useToast,
  Spinner,
  Alert,
  AlertIcon,
  AlertTitle,
  AlertDescription,
  SimpleGrid,
  Progress,
  useColorModeValue
} from '@chakra-ui/react'
import { ArrowBackIcon, ExternalLinkIcon } from '@chakra-ui/icons'
import { FaChartLine, FaPercent, FaCoins, FaTrendingUp } from 'react-icons/fa'
import axios from 'axios'
import Navigation from '../components/Navigation'
import StockChart from '../components/StockChart'
import { motion } from 'framer-motion'

const MotionBox = motion(Box)
const springy = { type: 'spring', stiffness: 260, damping: 22, mass: 0.7 }

export default function StockDetail() {
  const router = useRouter()
  const { stockName, symbol } = router.query
  const [stockData, setStockData] = useState(null)
  const [portfolioData, setPortfolioData] = useState(null)
  const [portfolioPercentage, setPortfolioPercentage] = useState(0)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const toast = useToast()

  const cardBg = useColorModeValue('white', 'gray.800')
  const borderColor = useColorModeValue('gray.200', 'gray.600')

  useEffect(() => {
    if (stockName && symbol) {
      fetchStockDetails()
    }
  }, [stockName, symbol])

  const fetchStockDetails = async () => {
    try {
      setLoading(true)
      setError(null)

      // Fetch portfolio data
      const portfolioResponse = await axios.get('http://localhost:5000/api/portfolio-with-live-prices')
      const allPortfolioData = portfolioResponse.data.portfolioData
      const summary = portfolioResponse.data.summary

      // Find the specific stock
      const stockPortfolioData = allPortfolioData.find(
        stock => stock.stockName === decodeURIComponent(stockName) && stock.symbol === symbol
      )

      if (!stockPortfolioData) {
        throw new Error('Stock not found in portfolio')
      }

      setPortfolioData(stockPortfolioData)

      // Calculate portfolio percentage
      const percentage = (stockPortfolioData.currentValue / summary.totalCurrentValue) * 100
      setPortfolioPercentage(percentage)

      // Fetch live stock data
      const pricesResponse = await axios.get('http://localhost:5000/api/prices')
      const priceData = pricesResponse.data.prices
      
      // Find stock in prices data
      const liveStockData = Object.entries(priceData).find(
        ([name, data]) => name === decodeURIComponent(stockName)
      )

      if (liveStockData) {
        setStockData({
          name: liveStockData[0],
          ...liveStockData[1]
        })
      }
    } catch (err) {
      setError('Failed to fetch stock details')
      console.error('Error fetching stock details:', err)
      toast({
        title: 'Error',
        description: 'Failed to fetch stock details',
        status: 'error',
        duration: 5000,
        isClosable: true,
      })
    } finally {
      setLoading(false)
    }
  }

  const handleChartClick = () => {
    if (symbol) {
      const tradingSymbol = symbol.replace('.NS', '')
      const tradingViewUrl = `https://www.tradingview.com/chart/?symbol=NSE%3A${tradingSymbol}&interval=1D`
      window.open(tradingViewUrl, '_blank')
    }
  }

  if (loading) {
    return (
      <Box minH="100vh" bg="gray.950">
        <Navigation />
        <Container maxW="container.xl" py={8}>
          <VStack spacing={6} align="stretch">
            <Box>
              <Box mb={4}>
                <Box h="12px" w="160px" bg="whiteAlpha.200" borderRadius="full" />
              </Box>
              <Box h="56px" bg="whiteAlpha.100" borderRadius="lg" />
            </Box>

            <SimpleGrid columns={{ base: 1, lg: 2 }} spacing={6}>
              <Box h="260px" bg="whiteAlpha.100" borderRadius="lg" />
              <Box h="260px" bg="whiteAlpha.100" borderRadius="lg" />
            </SimpleGrid>

            <Box h="340px" bg="whiteAlpha.100" borderRadius="lg" />
          </VStack>
        </Container>
      </Box>
    )
  }

  if (error || !portfolioData) {
    return (
      <Box minH="100vh" bg="gray.900">
        <Navigation />
        <Container maxW="container.xl" py={8}>
          <VStack spacing={6}>
            <Alert status="error" borderRadius="lg" maxW="md">
              <AlertIcon />
              <Box>
                <AlertTitle>Error!</AlertTitle>
                <AlertDescription>{error || 'Stock not found'}</AlertDescription>
              </Box>
            </Alert>
            <Button
              leftIcon={<ArrowBackIcon />}
              onClick={() => router.back()}
              colorScheme="blue"
            >
              Go Back
            </Button>
          </VStack>
        </Container>
      </Box>
    )
  }

  const isProfit = portfolioData.totalProfit >= 0
  const profitColor = isProfit ? 'green.400' : 'red.400'

  return (
    <Box minH="100vh" bg="gray.950">
      <Navigation />
      <Container maxW="container.xl" py={6}>
        <VStack spacing={6} align="stretch">
          {/* Header with shared element container */}
          <MotionBox
            layoutId={symbol ? `card-${symbol}` : undefined}
            transition={springy}
            borderRadius="xl"
            border="1px solid"
            borderColor={borderColor}
            p={4}
            bg={cardBg}
          >
            <Flex justify="space-between" align="center" flexWrap="wrap" gap={4}>
              <HStack spacing={4}>
                <Button
                  leftIcon={<ArrowBackIcon />}
                  variant="ghost"
                  colorScheme="blue"
                  onClick={() => router.back()}
                >
                  Back
                </Button>
                <VStack align="start" spacing={1}>
                  <Heading size="xl" color={useColorModeValue('gray.800', 'white')}>
                    {decodeURIComponent(stockName)}
                  </Heading>
                  <Badge colorScheme="blue" variant="solid" borderRadius="full" px={3} py={1}>
                    {symbol}
                  </Badge>
                </VStack>
              </HStack>
              
              <Button
                leftIcon={<ExternalLinkIcon />}
                rightIcon={<FaChartLine />}
                colorScheme="green"
                onClick={handleChartClick}
              >
                View Chart
              </Button>
            </Flex>
          </MotionBox>

          {/* Main Content Grid */}
          <SimpleGrid columns={{ base: 1, lg: 2 }} spacing={6}>
            {/* Left Column - Portfolio Information */}
            <VStack spacing={6} align="stretch">
              {/* Holdings Summary */}
              <Card bg={cardBg} borderColor={borderColor}>
                <CardBody>
                  <VStack spacing={4} align="stretch">
                    <Heading size="md" color={useColorModeValue('gray.800', 'white')}>
                      Holdings Summary
                    </Heading>
                    
                    <SimpleGrid columns={2} spacing={4}>
                      <Stat>
                        <StatLabel>Quantity</StatLabel>
                        <StatNumber>{portfolioData.quantity} shares</StatNumber>
                      </Stat>
                      
                      <Stat>
                        <StatLabel>Avg. Price</StatLabel>
                        <StatNumber>₹{portfolioData.avgPrice?.toLocaleString()}</StatNumber>
                      </Stat>
                      
                      <Stat>
                        <StatLabel>Invested Value</StatLabel>
                        <StatNumber>₹{portfolioData.investedValue?.toLocaleString()}</StatNumber>
                      </Stat>
                      
                      <Stat>
                        <StatLabel>Current Value</StatLabel>
                        <StatNumber>₹{portfolioData.currentValue?.toLocaleString()}</StatNumber>
                      </Stat>
                    </SimpleGrid>
                  </VStack>
                </CardBody>
              </Card>

              {/* P&L Analysis */}
              <Card bg={cardBg} borderColor={borderColor}>
                <CardBody>
                  <VStack spacing={4} align="stretch">
                    <Heading size="md" color={useColorModeValue('gray.800', 'white')}>
                      Profit & Loss Analysis
                    </Heading>
                    
                    <Box>
                      <Stat>
                        <StatLabel>Total P&L</StatLabel>
                        <StatNumber color={profitColor} fontSize="3xl">
                          {isProfit ? '+' : ''}₹{portfolioData.totalProfit?.toLocaleString() || '0'}
                        </StatNumber>
                        <StatHelpText fontSize="lg" color={profitColor}>
                          {isProfit ? '+' : ''}{portfolioData.profitPercent || 0}%
                        </StatHelpText>
                      </Stat>
                    </Box>

                    <Divider />

                    <SimpleGrid columns={1} spacing={3}>
                      <HStack justify="space-between">
                        <Text fontSize="sm" color={useColorModeValue('gray.600', 'gray.300')}>
                          Unrealized P&L
                        </Text>
                        <Text 
                          fontSize="sm" 
                          fontWeight="bold" 
                          color={portfolioData.unrealizedProfit >= 0 ? 'green.400' : 'red.400'}
                        >
                          {portfolioData.unrealizedProfit >= 0 ? '+' : ''}₹{portfolioData.unrealizedProfit?.toLocaleString() || '0'}
                        </Text>
                      </HStack>
                      
                      <HStack justify="space-between">
                        <Text fontSize="sm" color={useColorModeValue('gray.600', 'gray.300')}>
                          Dividend Received
                        </Text>
                        <Text fontSize="sm" fontWeight="bold" color="blue.400">
                          ₹{portfolioData.dividendTillNow?.toLocaleString() || '0'}
                        </Text>
                      </HStack>
                      
                      <HStack justify="space-between">
                        <Text fontSize="sm" color={useColorModeValue('gray.600', 'gray.300')}>
                          Realized P&L
                        </Text>
                        <Text fontSize="sm" fontWeight="bold" color="orange.400">
                          ₹{portfolioData.realized?.toLocaleString() || '0'}
                        </Text>
                      </HStack>
                    </SimpleGrid>
                  </VStack>
                </CardBody>
              </Card>

              {/* Portfolio Allocation */}
              <Card bg={cardBg} borderColor={borderColor}>
                <CardBody>
                  <VStack spacing={4} align="stretch">
                    <Heading size="md" color={useColorModeValue('gray.800', 'white')}>
                      Portfolio Allocation
                    </Heading>
                    
                    <Box>
                      <HStack justify="space-between" mb={2}>
                        <Text fontSize="sm" color={useColorModeValue('gray.600', 'gray.300')}>
                          Portfolio Weight
                        </Text>
                        <Text fontSize="lg" fontWeight="bold" color="purple.400">
                          {portfolioPercentage.toFixed(2)}%
                        </Text>
                      </HStack>
                      <Progress 
                        value={portfolioPercentage} 
                        colorScheme="purple" 
                        size="lg" 
                        borderRadius="full"
                      />
                      <Text fontSize="xs" color={useColorModeValue('gray.500', 'gray.400')} mt={1}>
                        This stock represents {portfolioPercentage.toFixed(2)}% of your total portfolio value
                      </Text>
                    </Box>
                  </VStack>
                </CardBody>
              </Card>
            </VStack>

            {/* Right Column - Live Price & Chart */}
            <VStack spacing={6} align="stretch">
              {/* Live Price Information */}
              {stockData && (
                <Card bg={cardBg} borderColor={borderColor}>
                  <CardBody>
                    <VStack spacing={4} align="stretch">
                      <Heading size="md" color={useColorModeValue('gray.800', 'white')}>
                        Live Market Data
                      </Heading>
                      
                      <Stat textAlign="center">
                        <StatLabel>Current Market Price</StatLabel>
                        <StatNumber fontSize="4xl" color={useColorModeValue('gray.800', 'white')}>
                          ₹{stockData.price?.toLocaleString()}
                        </StatNumber>
                        <StatHelpText 
                          fontSize="lg" 
                          color={stockData.change >= 0 ? 'green.400' : 'red.400'}
                        >
                          {stockData.change >= 0 ? '+' : ''}₹{stockData.change} 
                          ({stockData.change >= 0 ? '+' : ''}{stockData.changePercent}%)
                        </StatHelpText>
                      </Stat>

                      <Divider />

                      <SimpleGrid columns={2} spacing={4}>
                        <Box textAlign="center">
                          <Text fontSize="xs" color={useColorModeValue('gray.500', 'gray.400')} mb={1}>
                            PRICE VS AVG BUY
                          </Text>
                          <Text 
                            fontSize="lg" 
                            fontWeight="bold" 
                            color={stockData.price >= portfolioData.avgPrice ? 'green.400' : 'red.400'}
                          >
                            {stockData.price >= portfolioData.avgPrice ? 'Above' : 'Below'}
                          </Text>
                          <Text fontSize="sm" color={useColorModeValue('gray.600', 'gray.300')}>
                            ₹{Math.abs(stockData.price - portfolioData.avgPrice).toFixed(2)} difference
                          </Text>
                        </Box>

                        <Box textAlign="center">
                          <Text fontSize="xs" color={useColorModeValue('gray.500', 'gray.400')} mb={1}>
                            VALUE IMPACT
                          </Text>
                          <Text 
                            fontSize="lg" 
                            fontWeight="bold" 
                            color={stockData.change >= 0 ? 'green.400' : 'red.400'}
                          >
                            {stockData.change >= 0 ? '+' : ''}₹{(stockData.change * portfolioData.quantity).toLocaleString()}
                          </Text>
                          <Text fontSize="sm" color={useColorModeValue('gray.600', 'gray.300')}>
                            Today's impact
                          </Text>
                        </Box>
                      </SimpleGrid>
                    </VStack>
                  </CardBody>
                </Card>
              )}

              {/* Chart Section */}
              <Card bg={cardBg} borderColor={borderColor}>
                <CardBody>
                  <VStack spacing={4} align="stretch">
                    <HStack justify="space-between">
                      <Heading size="md" color={useColorModeValue('gray.800', 'white')}>
                        Price Chart
                      </Heading>
                      <Button
                        size="sm"
                        variant="outline"
                        colorScheme="blue"
                        rightIcon={<ExternalLinkIcon />}
                        onClick={handleChartClick}
                      >
                        Full Chart
                      </Button>
                    </HStack>
                    
                    <Box h="300px">
                      <StockChart symbol={symbol} />
                    </Box>
                  </VStack>
                </CardBody>
              </Card>

              {/* Quick Actions */}
              <Card bg={cardBg} borderColor={borderColor}>
                <CardBody>
                  <VStack spacing={4} align="stretch">
                    <Heading size="md" color={useColorModeValue('gray.800', 'white')}>
                      Quick Actions
                    </Heading>
                    
                    <SimpleGrid columns={1} spacing={3}>
                      <Button
                        leftIcon={<FaChartLine />}
                        variant="outline"
                        colorScheme="blue"
                        onClick={handleChartClick}
                      >
                        View Advanced Chart
                      </Button>
                      
                      <Button
                        leftIcon={<ArrowBackIcon />}
                        variant="outline"
                        colorScheme="gray"
                        onClick={() => router.push('/portfolio')}
                      >
                        View Full Portfolio
                      </Button>
                      
                      <Button
                        leftIcon={<ArrowBackIcon />}
                        variant="outline"
                        colorScheme="purple"
                        onClick={() => router.push('/')}
                      >
                        Back to Dashboard
                      </Button>
                    </SimpleGrid>
                  </VStack>
                </CardBody>
              </Card>
            </VStack>
          </SimpleGrid>
        </VStack>
      </Container>
    </Box>
  )
}
