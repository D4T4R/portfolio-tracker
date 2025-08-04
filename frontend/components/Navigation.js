import {
  Box,
  Flex,
  HStack,
  Link,
  Container,
  Heading,
  Text
} from '@chakra-ui/react'
import NextLink from 'next/link'

export default function Navigation() {
  return (
    <Box bg="gray.800" px={4} boxShadow="lg" borderBottom="1px solid" borderColor="gray.700">
      <Container maxW="container.xl">
        <Flex h={16} alignItems="center" justifyContent="space-between">
          <HStack spacing={8} alignItems="center">
            <NextLink href="/" passHref legacyBehavior>
              <Link _hover={{ textDecoration: 'none' }}>
                <Heading size="lg" color="blue.400">
                  Portfolio Tracker
                </Heading>
              </Link>
            </NextLink>
            <HStack as="nav" spacing={4}>
              <NextLink href="/" passHref legacyBehavior>
                <Link
                  px={3}
                  py={2}
                  rounded="md"
                  _hover={{
                    textDecoration: 'none',
                    bg: 'gray.700',
                  }}
                  color="white"
                >
                  Dashboard
                </Link>
              </NextLink>
              <NextLink href="/portfolio" passHref legacyBehavior>
                <Link
                  px={3}
                  py={2}
                  rounded="md"
                  _hover={{
                    textDecoration: 'none',
                    bg: 'gray.700',
                  }}
                  color="white"
                >
                  Portfolio Table
                </Link>
              </NextLink>
            </HStack>
          </HStack>
        </Flex>
      </Container>
    </Box>
  )
}
