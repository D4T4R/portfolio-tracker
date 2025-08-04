import { useState, useEffect } from 'react'
import {
  Box,
  Table,
  Thead,
  Tbody,
  Tr,
  Th,
  Td,
  TableCaption,
  useToast,
  IconButton,
  HStack,
  Text,
  Container,
  Heading,
  Button,
  Flex,
  Spinner
} from '@chakra-ui/react'
import { ChevronUpIcon, ChevronDownIcon, RepeatIcon } from '@chakra-ui/icons'
import axios from 'axios'
import Navigation from '../components/Navigation'

export default function PortfolioTable() {
  const [portfolioData, setPortfolioData] = useState([])
  const [filteredData, setFilteredData] = useState([])
  const [summaryData, setSummaryData] = useState(null)
  const [sortConfig, setSortConfig] = useState({ key: null, direction: 'asc' })
  const [error, setError] = useState(null)
  const [isLoading, setIsLoading] = useState(false)
  const toast = useToast()

  useEffect(() => {
    fetchPortfolioData(false) // false = don't show success toast on initial load
  }, [])

  const fetchPortfolioData = async (showSuccessToast = true) => {
    setIsLoading(true)
    setError(null)
    try {
      const response = await axios.get('http://localhost:5000/api/portfolio-with-live-prices')
      const allData = response.data.portfolioData
      const summary = response.data.summary
      
      // Filter out stocks with no value (quantity = 0 or no symbol)
      const filteredStocks = allData.filter(stock => 
        stock.quantity > 0 && stock.symbol && stock.symbol.trim() !== ''
      )
      
      setPortfolioData(allData)
      setFilteredData(filteredStocks)
      setSummaryData(summary)
      
      // Only show success toast on manual refresh
      if (showSuccessToast) {
        toast({
          title: 'Success',
          description: 'Portfolio data refreshed successfully!',
          status: 'success',
          duration: 3000,
          isClosable: true,
        })
      }
    } catch (err) {
      setError('Failed to fetch portfolio data')
      console.error('Error fetching portfolio data:', err)
      toast({
        title: 'Error',
        description: 'Failed to fetch portfolio data. Please try again later.',
        status: 'error',
        duration: 5000,
        isClosable: true,
      })
    } finally {
      setIsLoading(false)
    }
  }

  const handleSort = (key) => {
    let direction = 'asc'
    if (sortConfig.key === key && sortConfig.direction === 'asc') {
      direction = 'desc'
    }
    
    const sortedData = [...filteredData].sort((a, b) => {
      if (a[key] < b[key]) return direction === 'asc' ? -1 : 1
      if (a[key] > b[key]) return direction === 'asc' ? 1 : -1
      return 0
    })
    
    setFilteredData(sortedData)
    setSortConfig({ key, direction })
  }

  const SortableHeader = ({ children, sortKey, isNumeric = false }) => (
    <Th isNumeric={isNumeric}>
      <HStack spacing={1} justify={isNumeric ? 'flex-end' : 'flex-start'}>
        <Text>{children}</Text>
        <Box>
          <IconButton
            size="xs"
            variant="ghost"
            aria-label="Sort ascending"
            icon={<ChevronUpIcon />}
            onClick={() => handleSort(sortKey)}
            colorScheme={sortConfig.key === sortKey && sortConfig.direction === 'asc' ? 'blue' : 'gray'}
          />
          <IconButton
            size="xs"
            variant="ghost"
            aria-label="Sort descending"
            icon={<ChevronDownIcon />}
            onClick={() => handleSort(sortKey)}
            colorScheme={sortConfig.key === sortKey && sortConfig.direction === 'desc' ? 'blue' : 'gray'}
          />
        </Box>
      </HStack>
    </Th>
  )

  if (error) {
    return (
      <Box minH="100vh" bg="gray.900">
        <Navigation />
        <Container maxW="container.xl" py={8}>
          <Box bg="red.100" color="red.800" p={4} borderRadius="md">
            Error: {error}
          </Box>
        </Container>
      </Box>
    )
  }

  return (
    <Box minH="100vh" bg="gray.900">
      <Navigation />
      <Container maxW="90vw" py={6}>
        <Flex justify="space-between" align="center" mb={6}>
          <Heading size="xl" color="white">
            Portfolio Details
          </Heading>
          <Button
            leftIcon={isLoading ? <Spinner size="sm" /> : <RepeatIcon />}
            colorScheme="blue"
            variant="solid"
            onClick={fetchPortfolioData}
            isLoading={isLoading}
            loadingText="Refreshing..."
            size="md"
          >
            Refresh Prices
          </Button>
        </Flex>
        
        <Box overflowX="auto" bg="gray.800" borderRadius="lg" p={2}>
          <Table variant="simple" colorScheme="gray" size="sm">
            <Thead>
              <Tr>
                <SortableHeader sortKey="stockName">Stock</SortableHeader>
                <SortableHeader sortKey="avgPrice" isNumeric>Avg ₹</SortableHeader>
                <SortableHeader sortKey="initialQty" isNumeric>Init Qty</SortableHeader>
                <SortableHeader sortKey="quantity" isNumeric>Qty</SortableHeader>
                <SortableHeader sortKey="avgInvested" isNumeric>Invested</SortableHeader>
                <SortableHeader sortKey="currentPrice" isNumeric>CMP</SortableHeader>
                <SortableHeader sortKey="netValue" isNumeric>Net Value</SortableHeader>
                <SortableHeader sortKey="unrealizedProfit" isNumeric>Unrealized</SortableHeader>
                <SortableHeader sortKey="dividendTillNow" isNumeric>Dividend</SortableHeader>
                <SortableHeader sortKey="totalProfit" isNumeric>Total P&L</SortableHeader>
                <SortableHeader sortKey="profitPercent" isNumeric>P&L %</SortableHeader>
                <SortableHeader sortKey="realized" isNumeric>Realized</SortableHeader>
                <SortableHeader sortKey="bookedQty" isNumeric>Booked</SortableHeader>
              </Tr>
            </Thead>
            <Tbody>
              {filteredData.map((stock, index) => (
                <Tr key={index}>
                  <Td color="white">{stock.stockName}</Td>
                  <Td isNumeric color="white">₹{stock.avgPrice?.toLocaleString() || '0'}</Td>
                  <Td isNumeric color="white">{stock.initialQty?.toLocaleString() || '0'}</Td>
                  <Td isNumeric color="white">{stock.quantity?.toLocaleString() || '0'}</Td>
                  <Td isNumeric color="white">₹{stock.avgInvested?.toLocaleString() || '0'}</Td>
                  <Td isNumeric color="white">₹{stock.currentPrice?.toLocaleString() || '0'}</Td>
                  <Td isNumeric color="white">₹{stock.netValue?.toLocaleString() || '0'}</Td>
                  <Td isNumeric color={stock.unrealizedProfit >= 0 ? 'green.400' : 'red.400'}>
                    ₹{stock.unrealizedProfit?.toLocaleString() || '0'}
                  </Td>
                  <Td isNumeric color="blue.400">₹{stock.dividendTillNow?.toLocaleString() || '0'}</Td>
                  <Td isNumeric color={stock.totalProfit >= 0 ? 'green.400' : 'red.400'}>
                    ₹{stock.totalProfit?.toLocaleString() || '0'}
                  </Td>
                  <Td isNumeric color={stock.profitPercent >= 0 ? 'green.400' : 'red.400'}>
                    {stock.profitPercent || 0}%
                  </Td>
                  <Td isNumeric color="orange.400">₹{stock.realized?.toLocaleString() || '0'}</Td>
                  <Td isNumeric color="white">{stock.bookedQty?.toLocaleString() || '0'}</Td>
                </Tr>
              ))}
              
              {/* Total Row */}
              {summaryData && (
                <Tr bg="gray.700" fontWeight="bold">
                  <Td color="yellow.400" fontSize="lg">TOTAL</Td>
                  <Td></Td> {/* Avg Price */}
                  <Td></Td> {/* Initial Qty */}
                  <Td></Td> {/* Qty */}
                  <Td isNumeric color="white" fontSize="lg">₹{summaryData.totalInvestedValue.toLocaleString()}</Td> {/* Avg Invested */}
                  <Td></Td> {/* CMP */}
                  <Td isNumeric color="white" fontSize="lg">₹{summaryData.totalCurrentValue.toLocaleString()}</Td> {/* Net Value */}
                  <Td isNumeric color={summaryData.totalPnL >= 0 ? 'green.400' : 'red.400'} fontSize="lg">
                    ₹{summaryData.totalPnL.toLocaleString()}
                  </Td> {/* Unrealized Profit */}
                  <Td></Td> {/* Dividend Till Now */}
                  <Td isNumeric color={(summaryData.totalProfitSum || summaryData.totalPnL) >= 0 ? 'green.400' : 'red.400'} fontSize="lg">
                    ₹{(summaryData.totalProfitSum || summaryData.totalPnL).toLocaleString()}
                  </Td> {/* Total Profit */}
                  <Td isNumeric color={summaryData.totalPnLPercent >= 0 ? 'green.400' : 'red.400'} fontSize="lg">
                    {summaryData.totalPnLPercent}%
                  </Td> {/* Profit % */}
                  <Td></Td> {/* Realized */}
                  <Td></Td> {/* Booked Qty */}
                </Tr>
              )}
            </Tbody>
          </Table>
        </Box>
        
        {summaryData && (
          <Box mt={4} p={4} bg="gray.800" borderRadius="lg">
            <HStack justify="space-around" color="white">
              <Text>Total Stocks: <Text as="span" color="blue.400">{summaryData.totalStocks}</Text></Text>
              <Text>Gainers: <Text as="span" color="green.400">{summaryData.gainers}</Text></Text>
              <Text>Losers: <Text as="span" color="red.400">{summaryData.losers}</Text></Text>
            </HStack>
          </Box>
        )}
      </Container>
    </Box>
  )
}
